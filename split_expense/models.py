from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid

class Friendship(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="friends")
    friend = models.ForeignKey(User, on_delete=models.CASCADE, related_name="befriended_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'friend')

    def __str__(self):
        return f"{self.user.username} is friends with {self.friend.username}"

class FriendRequest(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_friend_requests")
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_friend_requests")
    created_at = models.DateTimeField(auto_now_add=True)
    is_accepted = models.BooleanField(default=False)

    class Meta:
        unique_together = ('sender', 'receiver')

    def __str__(self):
        return f"{self.sender.username} to {self.receiver.username} (Accepted: {self.is_accepted})"

class ExternalFriendInvitation(models.Model):
    """Tracks friend invitations sent to non-registered emails."""
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_external_invites")
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_joined = models.BooleanField(default=False)

    class Meta:
        unique_together = ('sender', 'email')

    def __str__(self):
        return f"{self.sender.username} invited {self.email}"

class Group(models.Model):
    name = models.CharField(max_length=100)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_groups")
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(User, through='GroupMember', related_name='expense_groups')
    color = models.CharField(max_length=20, default="#C8E64A")
    icon = models.CharField(max_length=50, default="groups")
    local_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)

    def __str__(self):
        return self.name

class GroupMember(models.Model):
    """
    Acts as the Virtual Ledger for the group, caching total_paid, total_owed, and net_balance per user.
    """
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Total money this user has paid for group expenses
    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Total money this user owes for their share of group expenses
    total_owed = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Net Balance = total_paid - total_owed
    # Positive -> Others owe them money
    # Negative -> They owe others money
    net_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Whether the user has accepted the invitation
    is_accepted = models.BooleanField(default=False)
    
    joined_at = models.DateTimeField(auto_now_add=True)
    
    # When the user was last sent an email reminder for owing money in this group
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    reminders_sent_today = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('group', 'user')
        
    def __str__(self):
        return f"{self.user.username} in {self.group.name} (Net: {self.net_balance})"

class GroupInvitation(models.Model):
    """
    Tracks pending invitations sent to unregistered email addresses via a special UUID token link.
    """
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='email_invitations')
    email = models.EmailField()
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_group_invitations')
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('group', 'email')
        
    def __str__(self):
        return f"{self.email} invited to {self.group.name}"

class Expense(models.Model):
    SPLIT_CHOICES = [
        ('equal', 'Equal'),
        ('exact', 'Exact Amount'),
        ('percentage', 'Percentage'),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="expenses")
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="paid_expenses")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="added_expenses", null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    split_type = models.CharField(max_length=20, choices=SPLIT_CHOICES, default='equal')
    date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    local_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)

    def __str__(self):
        return f"{self.description} ({self.amount}) paid by {self.paid_by.username}"

class ExpenseSplit(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="splits")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount_owed = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Only used if split_type is percentage, but helpful to store
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('expense', 'user')

    def __str__(self):
        return f"{self.user.username} owes {self.amount_owed} for {self.expense.description}"

class Settlement(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="settlements")
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="settlements_paid")
    paid_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name="settlements_received")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    local_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)

    def __str__(self):
        return f"{self.paid_by.username} paid {self.paid_to.username} {self.amount} in {self.group.name}"
