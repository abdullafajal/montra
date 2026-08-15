from decimal import Decimal
from django.db import transaction, models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from .models import (
    Group, GroupMember, Expense, ExpenseSplit, Settlement, 
    GroupInvitation, Friendship, FriendRequest, ExternalFriendInvitation
)

def send_friend_request(sender, receiver_email, request=None):
    """Sends a friend request or an external invitation."""
    receiver_email = receiver_email.strip().lower()
    
    # 1. Check if they are already friends
    receiver = User.objects.filter(Q(email__iexact=receiver_email) | Q(username__iexact=receiver_email)).first()
    if receiver:
        if receiver == sender:
            raise ValidationError("You cannot friend yourself.")
            
        if Friendship.objects.filter(user=sender, friend=receiver).exists():
            raise ValidationError(f"You are already friends with {receiver.username}.")
            
        # Check for existing request
        if FriendRequest.objects.filter(sender=sender, receiver=receiver).exists():
            raise ValidationError(f"A friend request to {receiver.username} is already pending.")
            
        # Create friend request
        request_obj = FriendRequest.objects.create(sender=sender, receiver=receiver)
        
        # Notify
        _send_friend_request_notification(request_obj)
        
        return request_obj
    else:
        # User not registered -> External Invite
        if ExternalFriendInvitation.objects.filter(sender=sender, email=receiver_email).exists():
            raise ValidationError(f"An invitation to {receiver_email} is already pending.")
            
        inv = ExternalFriendInvitation.objects.create(sender=sender, email=receiver_email)
        _send_external_invitation_email(inv, request=request)
        return inv

def _send_external_invitation_email(invitation, request=None):
    """Send an invitation email to a non-registered user."""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags
    from django.conf import settings as conf
    
    sender = invitation.sender
    email = invitation.email
    
    subject = f"Invitation to join Espere from {sender.username}"
    if request:
        from django.urls import reverse
        invite_url = request.build_absolute_uri(reverse('accounts:register')) + f"?email={email}"
    else:
        domain = getattr(conf, 'SITE_DOMAIN', 'espere.in')
        invite_url = f"https://{domain}/accounts/register/?email={email}"
    
    html_message = render_to_string('split_expense/email/friend_invitation.html', {
        'inviter': sender,
        'invite_url': invite_url
    })
    plain_message = strip_tags(html_message)
    
    try:
        send_mail(
            subject,
            plain_message,
            conf.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_message,
            fail_silently=True
        )
    except:
        pass

@transaction.atomic
def accept_friend_request(friend_request):
    """Accepts a friend request and creates bidirectional friendship."""
    if friend_request.is_accepted:
        return
        
    friend_request.is_accepted = True
    friend_request.save(update_fields=['is_accepted'])
    
    # Create bidirectional friendship
    Friendship.objects.get_or_create(user=friend_request.sender, friend=friend_request.receiver)
    Friendship.objects.get_or_create(user=friend_request.receiver, friend=friend_request.sender)
    
@transaction.atomic
def process_external_invite_signup(new_user):
    """Called after a new user signs up to check for pending external friend invites."""
    invites = ExternalFriendInvitation.objects.filter(email__iexact=new_user.email, is_joined=False)
    for invite in invites:
        # Auto-befriend
        Friendship.objects.get_or_create(user=invite.sender, friend=new_user)
        Friendship.objects.get_or_create(user=new_user, friend=invite.sender)
        
        invite.is_joined = True
        invite.save(update_fields=['is_joined'])
        
        # If the invite was also for a group, we should handle that too if we want, 
        # but the user only mentioned "Friends List" for signup.
        # Actually, let's check GroupInvitation too.
        group_invites = GroupInvitation.objects.filter(email__iexact=new_user.email)
        for g_invite in group_invites:
            GroupMember.objects.get_or_create(
                group=g_invite.group,
                user=new_user,
                defaults={'is_accepted': False} # They still need to accept the group invite
            )
            # We don't delete GroupInvitation yet because they might use the token link, 
            # but usually signup covers it.

def _send_friend_request_notification(friend_request):
    """Notify receiver about friend request."""
    sender = friend_request.sender
    receiver = friend_request.receiver
    
    subject = "New Friend Request"
    body = f"{sender.username} wants to be your friend on Espere."
    
    from accounts.models import DeviceToken
    from config.firebase import send_push_notification
    
    # Push
    tokens = DeviceToken.objects.filter(user=receiver)
    for dt in tokens:
        send_push_notification(token=dt.token, title=subject, body=body, data={"action": "open_friends"})

def invite_user_to_group(group, identifier, inviter, request=None):
    """
    Common invitation logic:
    1. If user exists in app -> Add to group (pending) and send push.
    2. If user doesn't exist -> Create GroupInvitation and send email.
    """
    from django.contrib.auth.models import User
    from .models import GroupMember, GroupInvitation
    from django.db.models import Q
    
    # Try to find user in app
    user_to_add = User.objects.filter(
        Q(username=identifier) | 
        Q(email__iexact=identifier) |
        Q(id=int(identifier) if identifier.isdigit() else -1)
    ).first()
    
    if user_to_add:
        if user_to_add == inviter:
            return False, "You cannot invite yourself."
            
        if GroupMember.objects.filter(group=group, user=user_to_add).exists():
            return False, f"{user_to_add.username} is already in the group."
            
        # Create membership
        GroupMember.objects.create(group=group, user=user_to_add, is_accepted=False)
        
        # Send notifications (Push)
        _send_group_invitation_notification(group, user_to_add, request=request)
        return True, f"Invitation sent to {user_to_add.username}."
    
    else:
        # Not in app
        if "@" not in identifier:
            return False, "User not found. Provide an email to invite them to the app."
            
        email = identifier.strip().lower()
        invite, created = GroupInvitation.objects.get_or_create(
            group=group,
            email=email,
            defaults={'invited_by': inviter}
        )
        
        _send_external_group_invitation_email(group, invite, inviter, request=request)
        return True, f"Invitation email sent to {email}."

def _send_group_invitation_notification(group, invited_user, request=None):
    """Notify app user about group invitation via Push and In-app notification."""
    sender = group.created_by
    subject = "New Group Invitation"
    body = f"{sender.username} invited you to join the group '{group.name}'."
    
    from accounts.models import DeviceToken, Notification
    from config.firebase import send_push_notification
    
    # In-app record
    Notification.objects.create(
        user=invited_user,
        title=subject,
        message=body,
        data={"action": "open_split_invitations", "group_id": str(group.id)}
    )
    
    # Push
    tokens = DeviceToken.objects.filter(user=invited_user)
    for dt in tokens:
        send_push_notification(
            token=dt.token, 
            title=subject, 
            body=body, 
            data={"action": "open_split_invitations", "group_id": str(group.id)}
        )

def _send_external_group_invitation_email(group, invite, inviter, request=None):
    """Send email to non-app user."""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags
    from django.conf import settings
    
    if request:
        domain = request.build_absolute_uri('/')[:-1]
    else:
        domain = f"https://{getattr(settings, 'SITE_DOMAIN', 'espere.in')}"
        
    link = f"{domain}/split/invite/{invite.token}/"
    
    subject = f"Invitation to join '{group.name}' on Espere"
    html_message = render_to_string('split_expense/email/group_invitation.html', {
        'group': group,
        'inviter': inviter,
        'invite_url': link
    })
    plain_message = strip_tags(html_message)
    
    send_mail(
        subject, plain_message, settings.DEFAULT_FROM_EMAIL,
        [invite.email], html_message=html_message
    )

@transaction.atomic
def create_expense(group, paid_by, amount, description, split_type, splits_data=None, local_id=None, created_by=None, date=None):
    """
    Creates an expense, calculates splits, and updates group member balances.
    
    splits_data format (optional, needed for exact/percentage):
    [
        {'user': user_instance, 'value': Decimal('100.00')}  # value is amount or percentage
    ]
    """
    amount = Decimal(str(amount))
    
    # 1. Create the Expense
    expense = Expense(
        group=group,
        paid_by=paid_by,
        created_by=created_by,
        amount=amount,
        description=description,
        split_type=split_type,
        local_id=local_id
    )
    if date:
        expense.date = date
    expense.save()
    
    members = list(group.members.all())
    num_members = len(members)
    
    if num_members == 0:
        raise ValidationError("Cannot create an expense in an empty group.")
        
    splits_to_create = []
    
    # 2. Calculate Splits
    if split_type == 'equal':
        # Split amount equally, adjust for rounding errors on the first person
        base_split = round(amount / num_members, 2)
        total_split = base_split * num_members
        difference = amount - total_split
        
        for i, member in enumerate(members):
            owed = base_split
            if i == 0:
                owed += difference  # Give the rounding difference to the first member
            
            splits_to_create.append(
                ExpenseSplit(expense=expense, user=member, amount_owed=owed)
            )
            
    elif split_type == 'exact':
        if not splits_data:
            raise ValidationError("Splits data is required for exact splits.")
            
        total_exact = sum(Decimal(str(item['value'])) for item in splits_data)
        if total_exact != amount:
            raise ValidationError(f"Total exact split ({total_exact}) must match expense amount ({amount}).")
            
        for item in splits_data:
            splits_to_create.append(
                ExpenseSplit(expense=expense, user=item['user'], amount_owed=Decimal(str(item['value'])))
            )
            
    elif split_type == 'percentage':
        if not splits_data:
            raise ValidationError("Splits data is required for percentage splits.")
            
        total_percent = sum(Decimal(str(item['value'])) for item in splits_data)
        if total_percent != Decimal('100'):
            raise ValidationError(f"Total percentage ({total_percent}) must equal 100%.")
            
        calculated_total = Decimal('0')
        for i, item in enumerate(splits_data):
            percent = Decimal(str(item['value']))
            owed = round(amount * (percent / Decimal('100')), 2)
            
            if i == len(splits_data) - 1:
                # Adjust rounding on the last person
                owed = amount - calculated_total
            else:
                calculated_total += owed
                
            splits_to_create.append(
                ExpenseSplit(expense=expense, user=item['user'], amount_owed=owed, percentage=percent)
            )
    else:
        raise ValidationError(f"Invalid split type: {split_type}")
        
    ExpenseSplit.objects.bulk_create(splits_to_create)
    
    # 3. Update the Virtual Ledger (GroupMember balances)
    # Update paid_by (total_paid)
    payer, _ = GroupMember.objects.get_or_create(group=group, user=paid_by)
    payer.total_paid += amount
    payer.net_balance += amount
    payer.save(update_fields=['total_paid', 'net_balance'])
    
    # Update all who owe
    for split in splits_to_create:
        member_ledger, _ = GroupMember.objects.get_or_create(group=group, user=split.user)
        member_ledger.total_owed += split.amount_owed
        member_ledger.net_balance -= split.amount_owed
        member_ledger.save(update_fields=['total_owed', 'net_balance'])

    # 4. Notifications
    _send_expense_notification(expense)

    return expense

def _send_expense_notification(expense):
    """Sends push and email notifications to group members about a new expense."""
    group = expense.group
    paid_by = expense.paid_by
    members = group.members.exclude(id=paid_by.id)
    
    subject = f"New Expense in {group.name}"
    body = f"{paid_by.username} added '{expense.description}' of {expense.amount} in {group.name}."
    
    from accounts.models import DeviceToken, Notification
    from config.firebase import send_push_notification
    from django.core.mail import send_mail
    from django.conf import settings
    from django.template.loader import render_to_string
    
    for member in members:
        # Create in-app notification
        Notification.objects.create(
            user=member,
            title=subject,
            message=body,
            data={
                "action": "open_split_group",
                "group_id": str(group.id),
                "expense_id": str(expense.id)
            }
        )

        # Push
        tokens = DeviceToken.objects.filter(user=member)
        for dt in tokens:
            send_push_notification(
                token=dt.token,
                title=subject,
                body=body,
                data={
                    "action": "open_split_group",
                    "group_id": str(group.id),
                    "expense_id": str(expense.id)
                }
            )

@transaction.atomic
def leave_group(group, user):
    """Handles a user leaving a group, including ownership transfer."""
    if not group.members.filter(id=user.id).exists():
        raise ValidationError("You are not a member of this group.")
        
    member = GroupMember.objects.get(group=group, user=user)
    if member.net_balance != 0:
        raise ValidationError("You must settle your balance before leaving the group.")
        
    # If they are the owner
    if group.created_by == user:
        other_members = group.members.exclude(id=user.id)
        if not other_members.exists():
            # Only member, delete group
            group.delete()
            return
        else:
            # Transfer ownership to most active member (most expenses paid)
            from django.db.models import Count
            most_active = other_members.annotate(
                expense_count=Count('paid_expenses', filter=models.Q(paid_expenses__group=group))
            ).order_by('-expense_count', 'groupmember__joined_at').first()
            
            group.created_by = most_active
            group.save(update_fields=['created_by'])
            
    member.delete()

def calculate_simplified_debts(group):
    """
    Returns a list of simplified transactions to settle all group debts.
    Format: [{'from': User, 'to': User, 'amount': Decimal}]
    """
    members = GroupMember.objects.filter(group=group).select_related('user')
    
    debtors = []   # People who owe money (net_balance < 0)
    creditors = [] # People who are owed money (net_balance > 0)
    
    for member in members:
        if member.net_balance < -Decimal('0.01'):
            debtors.append({'user': member.user, 'balance': abs(member.net_balance)})
        elif member.net_balance > Decimal('0.01'):
            creditors.append({'user': member.user, 'balance': member.net_balance})
            
    # Sort by largest balances first to optimize
    debtors.sort(key=lambda x: x['balance'], reverse=True)
    creditors.sort(key=lambda x: x['balance'], reverse=True)
    
    transactions = []
    
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]
        
        # Determine the minimum amount that can be settled between the two
        settle_amount = min(debtor['balance'], creditor['balance'])
        
        # Ensure we don't create 0 amount transactions (due to float precision)
        if settle_amount > Decimal('0.01'):
            transactions.append({
                'from': debtor['user'],
                'to': creditor['user'],
                'amount': round(settle_amount, 2)
            })
        
        # Deduct the settled amount
        debtor['balance'] -= settle_amount
        creditor['balance'] -= settle_amount
        
        if debtor['balance'] < Decimal('0.01'):
            i += 1
        if creditor['balance'] < Decimal('0.01'):
            j += 1
            
    return transactions

@transaction.atomic
def create_settlement(group, paid_by, paid_to, amount, local_id=None):
    """
    Records a settlement payment and updates the virtual ledger.
    """
    amount = Decimal(str(amount))
    
    settlement = Settlement.objects.create(
        group=group,
        paid_by=paid_by,
        paid_to=paid_to,
        amount=amount,
        local_id=local_id
    )
    
    # Adjust balances
    # The person paying is reducing their debt (they are "owed" back what they pay)
    payer_ledger, _ = GroupMember.objects.get_or_create(group=group, user=paid_by)
    payer_ledger.total_paid += amount
    payer_ledger.net_balance += amount
    payer_ledger.save(update_fields=['total_paid', 'net_balance'])
    
    # The person receiving is getting money (they "owe" the system what they receive)
    receiver_ledger, _ = GroupMember.objects.get_or_create(group=group, user=paid_to)
    receiver_ledger.total_owed += amount
    receiver_ledger.net_balance -= amount
    receiver_ledger.save(update_fields=['total_owed', 'net_balance'])
    
    return settlement

@transaction.atomic
def delete_expense(expense):
    """
    Reverses the ledger impact of an expense and deletes it.
    """
    group = expense.group
    amount = expense.amount
    
    # 1. Reverse the payer's total_paid and net_balance
    payer_ledger = GroupMember.objects.get(group=group, user=expense.paid_by)
    payer_ledger.total_paid -= amount
    payer_ledger.net_balance -= amount
    payer_ledger.save(update_fields=['total_paid', 'net_balance'])
    
    # 2. Reverse each split's impact on total_owed and net_balance
    for split in expense.splits.select_related('user'):
        member_ledger = GroupMember.objects.get(group=group, user=split.user)
        member_ledger.total_owed -= split.amount_owed
        member_ledger.net_balance += split.amount_owed
        member_ledger.save(update_fields=['total_owed', 'net_balance'])
    
    # 3. Delete the expense (cascades to ExpenseSplit)
    expense.delete()

@transaction.atomic
def update_expense(expense, paid_by, amount, description, split_type, splits_data=None, date=None):
    """
    Updates an expense by reversing the old ledger impact and creating a new one.
    Returns the new expense object.
    """
    group = expense.group
    
    # 1. Reverse the old expense's ledger impact
    old_amount = expense.amount
    
    payer_ledger = GroupMember.objects.get(group=group, user=expense.paid_by)
    payer_ledger.total_paid -= old_amount
    payer_ledger.net_balance -= old_amount
    payer_ledger.save(update_fields=['total_paid', 'net_balance'])
    
    for split in expense.splits.select_related('user'):
        member_ledger = GroupMember.objects.get(group=group, user=split.user)
        member_ledger.total_owed -= split.amount_owed
        member_ledger.net_balance += split.amount_owed
        member_ledger.save(update_fields=['total_owed', 'net_balance'])
    
    # 2. Delete the old expense
    expense.delete()
    
    # 3. Create the new expense using the existing service function
    return create_expense(
        group=group,
        paid_by=paid_by,
        amount=amount,
        description=description,
        split_type=split_type,
        splits_data=splits_data,
        date=date
    )

@transaction.atomic
def remove_member(group, user):
    """
    Removes a member from a group. Only allowed if their net balance is zero.
    """
    try:
        member = GroupMember.objects.get(group=group, user=user)
    except GroupMember.DoesNotExist:
        raise ValidationError("User is not a member of this group.")
    
    if member.net_balance != Decimal('0'):
        raise ValidationError(
            f"{user.get_full_name() or user.username} has an unsettled balance of "
            f"{member.net_balance}. Please settle all debts before removing."
        )
    
    # Delete the membership
    member.delete()
    
    # Also remove any pending invitation for this user's email
    if user.email:
        GroupInvitation.objects.filter(group=group, email=user.email).delete()

