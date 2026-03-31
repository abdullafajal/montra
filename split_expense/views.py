from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse
from .models import Group, GroupMember, Expense, Settlement
from .services import create_expense, calculate_simplified_debts, create_settlement
from decimal import Decimal, InvalidOperation

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
        return render(request, self.template_name)
        
    def post(self, request):
        name = request.POST.get('name')
        if not name:
            messages.error(request, "Group name is required.")
            return render(request, self.template_name)
            
        group = Group.objects.create(name=name, created_by=request.user)
        # Add creator to the group by default as accepted
        GroupMember.objects.create(group=group, user=request.user, is_accepted=True)
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
            paid_by = group.members.get(id=paid_by_id)
            
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
            
            if paid_by_id:
                paid_by = group.members.get(id=paid_by_id)
            else:
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
            
        return render(request, self.template_name, {'group': group})
        
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        identifier = request.POST.get('identifier', '').strip()
        if not identifier:
            messages.error(request, "Please enter an email or username.")
            return redirect('split_expense:group_member_add', group_id=group.id)
            
        # Try to find by username first, then by email
        user_to_add = User.objects.filter(username=identifier).first()
        if not user_to_add:
            user_to_add = User.objects.filter(email__iexact=identifier).first()
            
        is_new_user = False
        if not user_to_add:
            # Check if it's a valid email Address
            try:
                validate_email(identifier)
                # They don't have an account -> send special token invite
                from .models import GroupInvitation
                if GroupInvitation.objects.filter(group=group, email__iexact=identifier).exists():
                    messages.info(request, f"An invite is already pending for {identifier}.")
                    return redirect('split_expense:group_detail', pk=group.id)
                    
                invite = GroupInvitation.objects.create(
                    group=group,
                    email=identifier,
                    invited_by=request.user
                )
                
                # Send the special email using the new template
                from django.urls import reverse
                from django.template.loader import render_to_string
                from django.utils.html import strip_tags
                from django.core.mail import send_mail
                from django.conf import settings
                
                invite_url = request.build_absolute_uri(reverse('split_expense:invitation_special_link', args=[invite.token]))
                subject = f"{request.user.username} invited you to join '{group.name}' on Espere"
                html_message = render_to_string('split_expense/email/group_invitation.html', {
                    'group': group,
                    'inviter': request.user,
                    'invite_url': invite_url
                })
                plain_message = strip_tags(html_message)
                
                try:
                    send_mail(
                        subject,
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [identifier],
                        html_message=html_message,
                        fail_silently=False
                    )
                    messages.success(request, f"Invitation link successfully sent to {identifier}!")
                except Exception as e:
                    print(f"Failed to send invite email: {e}")
                    messages.warning(request, f"Created invite for {identifier} but failed to send the email.")
                
                return redirect('split_expense:group_detail', pk=group.id)
                
            except ValidationError:
                messages.error(request, f"User '{identifier}' not found and is not a valid email address.")
                return redirect('split_expense:group_member_add', group_id=group.id)
                
        # If user IS found (already registered user)
        if group.members.filter(id=user_to_add.id).exists():
            messages.info(request, f"{user_to_add.username} is already a member.")
            return redirect('split_expense:group_member_add', group_id=group.id)
            
        GroupMember.objects.create(group=group, user=user_to_add, is_accepted=False)
        
        # Send actual invitation email for registered user
        try:
            from django.urls import reverse
            from django.template.loader import render_to_string
            from django.utils.html import strip_tags
            from django.core.mail import send_mail
            from django.conf import settings
            
            subject = f"{request.user.username} invited you to '{group.name}'"
            groups_url = request.build_absolute_uri(reverse('split_expense:invitations'))
            
            html_message = render_to_string('split_expense/email/payment_reminder.html', {
                'title': "Group Invitation",
                'preheader': "You've been invited to join a split group.",
                'group_name': group.name,
                'message': f"<strong>{request.user.username}</strong> has invited you to join <strong>{group.name}</strong> on Espere to split expenses.<br><br>Log into your account to accept the invitation.",
                'action_url': groups_url,
                'action_text': "View Invitations",
                'footer_text': "If you weren't expecting this, you can safely ignore this email."
            })
            plain_message = strip_tags(html_message)
            
            send_mail(subject, plain_message, settings.DEFAULT_FROM_EMAIL, [user_to_add.email], html_message=html_message, fail_silently=True)
            messages.success(request, f"Invitation sent to {user_to_add.username}.")
        except Exception:
            messages.success(request, f"Added {user_to_add.username} to the group. They will need to accept the invite.")
            
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

from django.template.loader import render_to_string
from django.core.cache import cache

class SendReminderView(LoginRequiredMixin, View):
    def post(self, request, group_id):
        group = get_object_or_404(Group, pk=group_id)
        if not group.members.filter(id=request.user.id).exists():
            messages.error(request, "You are not a member of this group.")
            return redirect('split_expense:group_list')
            
        user_to_remind_id = request.POST.get('user_id')
        user_to_remind = get_object_or_404(User, id=user_to_remind_id)
        
        # Rate limit: 1 email per day (24 hours) via database persistent tracking
        membership = GroupMember.objects.filter(group=group, user=user_to_remind).first()
        if membership and membership.last_reminded_at:
            from django.utils import timezone
            if timezone.now() < membership.last_reminded_at + timezone.timedelta(hours=24):
                messages.warning(request, f"You can only send one email reminder to {user_to_remind.username} per day for this group. (Try sharing instead!)")
                return redirect(request.META.get('HTTP_REFERER', 'split_expense:group_detail'))
            
        amount_owed = request.POST.get('amount_owed', 'some amount')
        
        subject = f"Friendly Reminder: Action needed in '{group.name}'"
        
        html_message = render_to_string('split_expense/email/payment_reminder.html', {
            'user': user_to_remind,
            'sender_name': request.user.get_full_name() or request.user.username,
            'group_name': group.name,
            'amount_owed': amount_owed
        })
        
        try:
            from django.utils import timezone
            send_mail(
                subject=subject,
                message=f"Hi {user_to_remind.username},\n\nJust a quick reminder regarding your balance in '{group.name}'.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user_to_remind.email],
                html_message=html_message,
                fail_silently=False
            )
            
            # Persist the lock for 24 hours in the database
            if membership:
                membership.last_reminded_at = timezone.now()
                membership.save()
                
            messages.success(request, f"Reminder email successfully sent to {user_to_remind.username}.")
        except Exception as e:
            messages.error(request, f"Failed to send reminder email. Reason: {e}")
            
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
        
        return render(request, self.template_name, {
            'group': group,
            'expense': expense,
            'splits': splits
        })

