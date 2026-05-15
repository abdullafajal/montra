from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse
from .models import Group, GroupMember, Expense, Settlement, Friendship, FriendRequest, ExternalFriendInvitation
from .services import (
    create_expense, calculate_simplified_debts, create_settlement, 
    delete_expense, update_expense, remove_member,
    send_friend_request, accept_friend_request, process_external_invite_signup
)
from decimal import Decimal, InvalidOperation
from django.utils.html import strip_tags
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

class FriendListView(LoginRequiredMixin, ListView):
    template_name = 'split_expense/friend_list.html'
    context_object_name = 'friendships'
    
    def get_queryset(self):
        return Friendship.objects.filter(user=self.request.user).select_related('friend')
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pending_requests'] = FriendRequest.objects.filter(receiver=self.request.user, is_accepted=False)
        context['sent_requests'] = FriendRequest.objects.filter(sender=self.request.user, is_accepted=False)
        context['external_invites'] = ExternalFriendInvitation.objects.filter(sender=self.request.user, is_joined=False)
        return context

class SendFriendRequestView(LoginRequiredMixin, View):
    def post(self, request):
        email = request.POST.get('email', '').strip()
        if not email:
            messages.error(request, "Email is required.")
            return redirect('split_expense:friend_list')
            
        try:
            result = send_friend_request(request.user, email, request=request)
            if isinstance(result, FriendRequest):
                messages.success(request, f"Friend request sent to {result.receiver.username}.")
            else:
                # External invite
                invite_url = request.build_absolute_uri(reverse('accounts:register'))
                subject = f"{request.user.username} invited you to join Espere"
                html_message = render_to_string('split_expense/email/friend_invitation.html', {
                    'inviter': request.user,
                    'invite_url': invite_url
                })
                plain_message = strip_tags(html_message)
                
                try:
                    send_mail(
                        subject,
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        html_message=html_message,
                        fail_silently=False
                    )
                    messages.success(request, f"Invitation sent to {email}. They will be your friend once they sign up.")
                except Exception as e:
                    messages.warning(request, f"Invitation created for {email}, but failed to send email.")
                    
        except ValidationError as e:
            messages.error(request, str(e.message))
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            
        return redirect('split_expense:friend_list')

class FriendRequestActionView(LoginRequiredMixin, View):
    def post(self, request, request_id, action):
        friend_request = get_object_or_404(FriendRequest, id=request_id)
        
        if action == 'accept':
            if friend_request.receiver != request.user:
                messages.error(request, "Not authorized.")
            else:
                accept_friend_request(friend_request)
                messages.success(request, f"You are now friends with {friend_request.sender.username}!")
                
        elif action == 'reject':
            if friend_request.receiver != request.user:
                messages.error(request, "Not authorized.")
            else:
                friend_request.delete()
                messages.success(request, "Friend request rejected.")
                
        elif action == 'cancel':
            if friend_request.sender != request.user:
                messages.error(request, "Not authorized.")
            else:
                friend_request.delete()
                messages.success(request, "Friend request cancelled.")
                
        return redirect('split_expense:friend_list')

class GroupListView(LoginRequiredMixin, ListView):
    model = Group
    template_name = 'split_expense/group_list.html'
    context_object_name = 'groups'
    
    def get_queryset(self):
        # Only show groups where they have ACCEPTED the invite
        from django.db.models import OuterRef, Subquery
        user_balance_sq = GroupMember.objects.filter(
            group=OuterRef('pk'), 
            user=self.request.user
        ).values('net_balance')[:1]
        
        return Group.objects.filter(
            members=self.request.user, 
            groupmember__user=self.request.user, 
            groupmember__is_accepted=True
        ).annotate(
            my_net_balance=Subquery(user_balance_sq)
        ).order_by('-created_at')
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass the count of pending invitations
        context['pending_invites'] = GroupMember.objects.filter(user=self.request.user, is_accepted=False).count()
        return context

class GroupCreateView(LoginRequiredMixin, View):
    template_name = 'split_expense/group_form.html'
    
    def get(self, request):
        friend_ids = request.GET.getlist('friend_ids')
        friends = []
        if friend_ids:
            friends = Friendship.objects.filter(user=request.user, friend_id__in=friend_ids).select_related('friend')
            
        return render(request, self.template_name, {
            'preselected_friends': friends
        })
        
    def post(self, request):
        name = request.POST.get('name')
        friend_ids = request.POST.getlist('friend_ids')
        
        if not name:
            messages.error(request, "Group name is required.")
            return redirect('split_expense:group_create')
            
        group = Group.objects.create(name=name, created_by=request.user)
        # Add creator as accepted
        GroupMember.objects.create(group=group, user=request.user, is_accepted=True)
        
        # Add pre-selected friends
        count = 0
        for fid in friend_ids:
            friendship = Friendship.objects.filter(user=request.user, friend_id=fid).first()
            if friendship:
                GroupMember.objects.create(group=group, user=friendship.friend, is_accepted=False)
                count += 1
                
        if count > 0:
            messages.success(request, f"Group '{name}' created and {count} friends invited.")
        else:
            messages.success(request, f"Group '{name}' created successfully.")
            
        return redirect('split_expense:group_detail', pk=group.pk)

class GroupDetailView(LoginRequiredMixin, DetailView):
    model = Group
    template_name = 'split_expense/group_detail.html'
    context_object_name = 'group'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group = self.object
        
        # Verify user is in group
        if not group.members.filter(id=self.request.user.id).exists():
            messages.error(self.request, "You are not a member of this group.")
            return context # Will handle redirect or error in get() later usually, but simplifying here.
            
        context['expenses'] = group.expenses.all().order_by('-created_at')
        context['members'] = GroupMember.objects.filter(group=group).select_related('user')
        from .models import GroupInvitation
        context['pending_invitations'] = GroupInvitation.objects.filter(group=group)
        context['simplified_debts'] = calculate_simplified_debts(group)
        
        try:
            context['my_ledger'] = GroupMember.objects.get(group=group, user=self.request.user)
        except GroupMember.DoesNotExist:
            context['my_ledger'] = None
            
        return context

class ExpenseCreateView(LoginRequiredMixin, View):
    template_name = 'split_expense/expense_form.html'
    
    def get(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        context = {
            'group': group,
            'members': group.members.all()
        }
        return render(request, self.template_name, context)
        
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        
        description = request.POST.get('description')
        amount_str = request.POST.get('amount')
        paid_by_id = request.POST.get('paid_by')
        split_type = request.POST.get('split_type', 'equal')
        
        try:
            amount = Decimal(amount_str)
            paid_by = request.user

            
            splits_data = []
            if split_type in ['exact', 'percentage']:
                for member in group.members.all():
                    val = request.POST.get(f'split_val_{member.id}')
                    if val:
                        splits_data.append({
                            'user': member,
                            'value': Decimal(val)
                        })
            
            create_expense(
                group=group,
                paid_by=paid_by,
                amount=amount,
                description=description,
                split_type=split_type,
                splits_data=splits_data
            )
            messages.success(request, "Expense added successfully.")
            return redirect('split_expense:group_detail', pk=group.id)
            
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('split_expense:expense_create', group_id=group.id)

from django.core.mail import send_mail
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string

class SettlementCreateView(LoginRequiredMixin, View):
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        paid_to_id = request.POST.get('paid_to')
        paid_by_id = request.POST.get('paid_by')
        amount_str = request.POST.get('amount')
        
        try:
            amount = Decimal(amount_str)
            paid_to = group.members.get(id=paid_to_id)
            
            paid_by = request.user
                
            if request.user != paid_by and request.user != paid_to and request.user != group.created_by:
                raise Exception("You don't have permission to record this settlement.")
                
            create_settlement(
                group=group,
                paid_by=paid_by,
                paid_to=paid_to,
                amount=amount
            )
            
            if request.user == group.created_by and request.user not in [paid_by, paid_to]:
                messages.success(request, f"Settlement recorded: {amount} from {paid_by.username} to {paid_to.username}.")
            else:
                messages.success(request, f"Successfully settled {amount}.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            
        return redirect('split_expense:group_detail', pk=group.id)

class GroupMemberAddView(LoginRequiredMixin, View):
    template_name = 'split_expense/member_add_form.html'
    
    def get(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        # Get friends who are NOT already members or invited
        member_ids = group.members.values_list('id', flat=True)
        friends = Friendship.objects.filter(user=request.user).exclude(friend_id__in=member_ids).select_related('friend')
        
        return render(request, self.template_name, {
            'group': group,
            'friends': friends
        })
        
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        user_ids = request.POST.getlist('user_ids')
        if not user_ids:
            messages.error(request, "Please select at least one friend to invite.")
            return redirect('split_expense:group_member_add', group_id=group.id)
            
        count = 0
        for uid in user_ids:
            friendship = Friendship.objects.filter(user=request.user, friend_id=uid).first()
            if friendship:
                user_to_add = friendship.friend
                if not group.members.filter(id=user_to_add.id).exists():
                    GroupMember.objects.create(group=group, user=user_to_add, is_accepted=False)
                    count += 1
                    
                    # Send invitation email
                    try:
                        subject = f"{request.user.username} invited you to '{group.name}'"
                        invite_url = request.build_absolute_uri(reverse('split_expense:invitations'))
                        html_message = render_to_string('split_expense/email/group_invitation.html', {
                            'inviter': request.user,
                            'group': group,
                            'invite_url': invite_url,
                        })
                        send_mail(subject, strip_tags(html_message), settings.DEFAULT_FROM_EMAIL, [user_to_add.email], html_message=html_message, fail_silently=True)
                    except Exception:
                        pass
        
        if count > 0:
            messages.success(request, f"Invitations sent to {count} friends.")
        else:
            messages.info(request, "No new invitations sent.")
            
        return redirect('split_expense:group_detail', pk=group.id)

class InvitationListView(LoginRequiredMixin, ListView):
    template_name = 'split_expense/invitation_list.html'
    context_object_name = 'invitations'
    
    def get_queryset(self):
        return GroupMember.objects.filter(user=self.request.user, is_accepted=False).select_related('group')

class InvitationActionView(LoginRequiredMixin, View):
    def post(self, request, group_id, action):
        membership = get_object_or_404(GroupMember, group_id=group_id, user=request.user)
        
        if membership.is_accepted:
            messages.info(request, "You have already accepted this invitation.")
            return redirect('split_expense:group_detail', pk=group_id)
            
        if action == 'accept':
            membership.is_accepted = True
            membership.save(update_fields=['is_accepted'])
            messages.success(request, f"You have successfully joined {membership.group.name}.")
            return redirect('split_expense:group_detail', pk=group_id)
            
        elif action == 'reject':
            membership.delete()
            messages.success(request, f"You rejected the invitation to {membership.group.name}.")
            return redirect('split_expense:group_list')
            
        return redirect('split_expense:invitations')

from .models import GroupInvitation

class InvitationAcceptSpecialView(View):
    def get(self, request, token):
        invite = get_object_or_404(GroupInvitation, token=token)
        
        if request.user.is_authenticated:
            # Ensure email matches
            if request.user.email.lower() == invite.email.lower():
                # Add them to the group
                GroupMember.objects.get_or_create(
                    group=invite.group,
                    user=request.user,
                    defaults={'is_accepted': True}
                )
                
                messages.success(request, f"You successfully joined {invite.group.name}!")
                invite.delete()
                return redirect('split_expense:group_detail', pk=invite.group.id)
            else:
                messages.error(request, f"This invitation was sent to {invite.email}, but you are logged in as {request.user.email}. Please log in with the correct account.")
                return redirect('transactions:dashboard')
        else:
            # Store in session and redirect to register
            request.session['invite_token'] = str(token)
            request.session['invite_email'] = invite.email
            messages.info(request, f"You've been invited to join {invite.group.name}! Please create an account to view and share expenses.")
            
            return redirect('accounts:register')

class SendReminderView(LoginRequiredMixin, View):
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        user_to_remind_id = request.POST.get('user_id')
        user_to_remind = get_object_or_404(User, id=user_to_remind_id)
        
        # Rate limit: 3 per 24 hours
        now = timezone.now()

        membership = GroupMember.objects.filter(group=group, user=user_to_remind).first()
        if membership:
            if membership.last_reminded_at and now >= membership.last_reminded_at + timezone.timedelta(hours=24):
                membership.reminders_sent_today = 0
            
            if membership.reminders_sent_today >= 3:
                messages.warning(request, f"You can only send 3 reminders to {user_to_remind.username} per day for this group. (Try sharing instead!)")
                return redirect(request.META.get('HTTP_REFERER', 'split_expense:group_detail'))
            
        amount_owed = request.POST.get('amount_owed', 'some amount')
        
        subject = f"Action needed in '{group.name}'"
        email_body_text = f"Hi {user_to_remind.username},\n\nJust a quick reminder regarding your balance in '{group.name}'.\n\nPlease settle up when you can!"
        push_body_text = f"Just a reminder regarding your balance of {amount_owed}. Please settle up!"
        
        pushed = False
        from accounts.models import DeviceToken, Notification
        from config.firebase import send_push_notification
        
        # Create in-app notification
        Notification.objects.create(
            user=user_to_remind,
            title=subject,
            message=push_body_text,
            data={
                "action": "open_split_group",
                "group_id": str(group.id),
                "group_name": group.name,
            }
        )

        tokens = DeviceToken.objects.filter(user=user_to_remind)
        if tokens.exists():
            for dt in tokens:
                success = send_push_notification(
                    token=dt.token, 
                    title=subject, 
                    body=push_body_text,
                    data={
                        "action": "open_split_group",
                        "group_id": str(group.id),
                        "group_name": group.name,
                    }
                )
                if success:
                    pushed = True

        print(f"[DEBUG FCM WEB] Push notification successful: {pushed}")
        if not pushed:
            html_message = render_to_string('split_expense/email/payment_reminder.html', {
                'user': user_to_remind,
                'sender_name': request.user.get_full_name() or request.user.username,
                'group_name': group.name,
                'amount_owed': amount_owed
            })
            
            try:
                from django.conf import settings as conf
                send_mail(
                    subject=subject,
                    message=email_body_text,
                    from_email=conf.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_to_remind.email],
                    html_message=html_message,
                    fail_silently=False
                )
            except Exception as e:
                messages.error(request, f"Failed to send reminder email. Reason: {e}")
                return redirect(request.META.get('HTTP_REFERER', 'split_expense:group_detail'))
            
        if membership:
            if membership.reminders_sent_today == 0 or membership.last_reminded_at is None:
                membership.last_reminded_at = now
            membership.reminders_sent_today += 1
            membership.save()
            
        msg = "Push notification successfully sent" if pushed else "Reminder email successfully sent"
        messages.success(request, f"{msg} to {user_to_remind.username}.")
        return redirect(request.META.get('HTTP_REFERER', 'split_expense:group_detail'))

from django.http import JsonResponse
from django.db.models import Q

class SettlementConfirmView(LoginRequiredMixin, View):
    def get(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        
        # We expect paid_by, paid_to, amount in GET
        paid_by_id = request.GET.get('paid_by')
        paid_to_id = request.GET.get('paid_to')
        amount = request.GET.get('amount')
        
        paid_by = get_object_or_404(User, id=paid_by_id)
        paid_to = get_object_or_404(User, id=paid_to_id)
        
        return render(request, 'split_expense/settlement_confirm.html', {
            'group': group,
            'paid_by': paid_by,
            'paid_to': paid_to,
            'amount': amount,
        })

class ReminderConfirmView(LoginRequiredMixin, View):
    def get(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        
        user_id = request.GET.get('user_id')
        amount_owed = request.GET.get('amount_owed')
        
        user_to_remind = get_object_or_404(User, id=user_id)
        
        return render(request, 'split_expense/reminder_confirm.html', {
            'group': group,
            'user_to_remind': user_to_remind,
            'amount_owed': amount_owed,
        })

class UserSearchAPIView(LoginRequiredMixin, View):
    def get(self, request):
        query = request.GET.get('q', '').strip()
        if len(query) < 2:
            return JsonResponse({'users': []})
            
        # Exclude inactive shadow users
        users = User.objects.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
        ).exclude(id=request.user.id).exclude(is_active=False)[:5]
        
        results = []
        for u in users:
            results.append({
                'username': u.username,
                'email': u.email,
                'initial': u.username[0].upper()
            })
            
        return JsonResponse({'users': results})

class ExpenseDetailView(LoginRequiredMixin, View):
    template_name = 'split_expense/expense_detail.html'
    
    def get(self, request, group_id, expense_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        expense = get_object_or_404(Expense, pk=expense_id, group=group)
        splits = expense.splits.select_related('user').all()
        
        can_edit = (request.user == expense.paid_by or request.user == group.created_by)
        
        return render(request, self.template_name, {
            'group': group,
            'expense': expense,
            'splits': splits,
            'can_edit': can_edit
        })

class ExpenseUpdateView(LoginRequiredMixin, View):
    template_name = 'split_expense/expense_form.html'
    
    def get(self, request, group_id, expense_id):
        group = get_object_or_404(Group, pk=group_id)
        expense = get_object_or_404(Expense, pk=expense_id, group=group)
        
        if request.user != expense.paid_by and request.user != group.created_by:
            messages.error(request, "You don't have permission to edit this expense.")
            return redirect('split_expense:expense_detail', group_id=group.id, expense_id=expense.id)
        
        context = {
            'group': group,
            'members': group.members.all(),
            'expense': expense,
            'splits': {s.user_id: s for s in expense.splits.all()},
            'is_edit': True
        }
        return render(request, self.template_name, context)
    
    def post(self, request, group_id, expense_id):
        group = get_object_or_404(Group, pk=group_id)
        expense = get_object_or_404(Expense, pk=expense_id, group=group)
        
        if request.user != expense.paid_by and request.user != group.created_by:
            messages.error(request, "You don't have permission to edit this expense.")
            return redirect('split_expense:expense_detail', group_id=group.id, expense_id=expense.id)
        
        description = request.POST.get('description')
        amount_str = request.POST.get('amount')
        paid_by_id = request.POST.get('paid_by')
        split_type = request.POST.get('split_type', 'equal')
        
        try:
            amount = Decimal(amount_str)
            paid_by = request.user

            
            splits_data = []
            if split_type in ['exact', 'percentage']:
                for member in group.members.all():
                    val = request.POST.get(f'split_val_{member.id}')
                    if val:
                        splits_data.append({
                            'user': member,
                            'value': Decimal(val)
                        })
            
            new_expense = update_expense(
                expense=expense,
                paid_by=paid_by,
                amount=amount,
                description=description,
                split_type=split_type,
                splits_data=splits_data
            )
            messages.success(request, "Expense updated successfully.")
            return redirect('split_expense:expense_detail', group_id=group.id, expense_id=new_expense.id)
            
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('split_expense:expense_edit', group_id=group.id, expense_id=expense.id)

class ExpenseDeleteView(LoginRequiredMixin, View):
    def post(self, request, group_id, expense_id):
        group = get_object_or_404(Group, pk=group_id)
        expense = get_object_or_404(Expense, pk=expense_id, group=group)
        
        if request.user != expense.paid_by and request.user != group.created_by:
            messages.error(request, "You don't have permission to delete this expense.")
            return redirect('split_expense:expense_detail', group_id=group.id, expense_id=expense.id)
        
        try:
            delete_expense(expense)
            messages.success(request, "Expense deleted and balances restored.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        
        return redirect('split_expense:group_detail', pk=group.id)

class GroupUpdateView(LoginRequiredMixin, View):
    template_name = 'split_expense/group_form.html'
    
    def get(self, request, pk):
        group = get_object_or_404(Group, pk=pk)
        if request.user != group.created_by:
            messages.error(request, "Only the group creator can edit this group.")
            return redirect('split_expense:group_detail', pk=group.pk)
        
        return render(request, self.template_name, {'group': group, 'is_edit': True})
    
    def post(self, request, pk):
        group = get_object_or_404(Group, pk=pk)
        if request.user != group.created_by:
            messages.error(request, "Only the group creator can edit this group.")
            return redirect('split_expense:group_detail', pk=group.pk)
        
        name = request.POST.get('name')
        if not name:
            messages.error(request, "Group name is required.")
            return render(request, self.template_name, {'group': group, 'is_edit': True})
        
        group.name = name
        group.save(update_fields=['name'])
        messages.success(request, f"Group renamed to '{name}'.")
        return redirect('split_expense:group_detail', pk=group.pk)

class GroupMemberRemoveView(LoginRequiredMixin, View):
    def post(self, request, group_id, user_id):
        group = get_object_or_404(Group, pk=group_id)
        
        if request.user != group.created_by:
            messages.error(request, "Only the group creator can remove members.")
            return redirect('split_expense:group_detail', pk=group.id)
        
        if user_id == request.user.id:
            messages.error(request, "You cannot remove yourself from the group.")
            return redirect('split_expense:group_detail', pk=group.id)
        
        user_to_remove = get_object_or_404(User, pk=user_id)
        
        try:
            remove_member(group, user_to_remove)
            messages.success(request, f"{user_to_remove.get_full_name() or user_to_remove.username} has been removed from the group.")
        except ValidationError as e:
            messages.error(request, str(e.message))
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        
        return redirect('split_expense:group_detail', pk=group.id)

class GroupLeaveView(LoginRequiredMixin, View):
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        try:
            from .services import leave_group
            leave_group(group, request.user)
            messages.success(request, f"You have left the group '{group.name}'.")
        except ValidationError as e:
            messages.error(request, str(e.message))
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            
        return redirect('split_expense:group_list')


class GroupDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        group = get_object_or_404(Group, pk=pk)
        
        # Check if owner
        if group.created_by != request.user:
            messages.error(request, "Only the group owner can delete the group.")
            return redirect('split_expense:group_detail', pk=group.id)
            
        # Check if all members are settled
        if GroupMember.objects.filter(group=group).exclude(net_balance=0).exists():
            messages.error(request, "Cannot delete group with outstanding balances.")
            return redirect('split_expense:group_detail', pk=group.id)
            
        group.delete()
        messages.success(request, f"Group '{group.name}' has been deleted.")
        return redirect('split_expense:group_list')
