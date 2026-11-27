"""Accounts models — UserProfile for preferences."""
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class UserProfile(models.Model):
    CURRENCY_CHOICES = [
        ("USD", "US Dollar ($)"),
        ("EUR", "Euro (€)"),
        ("GBP", "British Pound (£)"),
        ("INR", "Indian Rupee (₹)"),
        ("JPY", "Japanese Yen (¥)"),
        ("CAD", "Canadian Dollar (C$)"),
        ("AUD", "Australian Dollar (A$)"),
        ("PKR", "Pakistani Rupee (Rs)"),
    ]

    THEME_CHOICES = [
        ("light", "Light"),
        ("dark", "Dark"),
    ]

    CURRENCY_SYMBOLS = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "INR": "₹",
        "JPY": "¥",
        "CAD": "C$",
        "AUD": "A$",
        "PKR": "Rs",
    }

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="INR")
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="light")
    email_reminders = models.BooleanField(default=True, help_text="Receive daily reminders to log expenses.")
    # One spending limit for the whole month (0 = none; then the category budgets add up).
    monthly_budget = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_currency_symbol(self):
        return self.CURRENCY_SYMBOLS.get(self.currency, "₹")

    def __str__(self):
        return f"{self.user.username}'s Profile"


import random

def generate_otp():
    return str(random.randint(100000, 999999))

class EmailVerificationToken(models.Model):
    """One-time token for verifying a user's email address."""
    MAX_ATTEMPTS = 3
    COOLDOWN_HOURS = 24

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="verification_token")
    token = models.CharField(max_length=6, default=generate_otp)
    attempt_count = models.PositiveIntegerField(default=1)
    last_sent_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def can_resend(self):
        """Check if resend is allowed (under 3 attempts or 24h cooldown passed)."""
        if self.attempt_count < self.MAX_ATTEMPTS:
            return True
        # After 3 attempts, must wait 24 hours from last send
        cooldown_end = self.last_sent_at + timezone.timedelta(hours=self.COOLDOWN_HOURS)
        if timezone.now() >= cooldown_end:
            return True
        return False

    def get_cooldown_remaining(self):
        """Return human-readable time remaining for cooldown."""
        if self.attempt_count < self.MAX_ATTEMPTS:
            return None
        cooldown_end = self.last_sent_at + timezone.timedelta(hours=self.COOLDOWN_HOURS)
        remaining = cooldown_end - timezone.now()
        if remaining.total_seconds() <= 0:
            return None
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def __str__(self):
        return f"Verification token for {self.user.username}"


class PasswordResetToken(models.Model):
    """One-time token for resetting a user's password."""
    MAX_ATTEMPTS = 3
    COOLDOWN_HOURS = 24

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="password_reset_token")
    token = models.CharField(max_length=6, default=generate_otp)
    attempt_count = models.PositiveIntegerField(default=1)
    last_sent_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def can_resend(self):
        """Check if resend is allowed (under 3 attempts or 24h cooldown passed)."""
        if self.attempt_count < self.MAX_ATTEMPTS:
            return True
        cooldown_end = self.last_sent_at + timezone.timedelta(hours=self.COOLDOWN_HOURS)
        if timezone.now() >= cooldown_end:
            return True
        return False

    def get_cooldown_remaining(self):
        """Return human-readable time remaining for cooldown."""
        if self.attempt_count < self.MAX_ATTEMPTS:
            return None
        cooldown_end = self.last_sent_at + timezone.timedelta(hours=self.COOLDOWN_HOURS)
        remaining = cooldown_end - timezone.now()
        if remaining.total_seconds() <= 0:
            return None
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def __str__(self):
        return f"Password reset token for {self.user.username}"


class DeviceToken(models.Model):
    """Stores Firebase Cloud Messaging (FCM) tokens for push notifications."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Device token for {self.user.username}"


class Notification(models.Model):
    # Notifications older than this are removed (see prune()).
    KEEP_DAYS = 90

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=255)
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    # Set by the app for notifications it made itself (daily reminders, budget alerts),
    # so saving the same one twice keeps one copy.
    client_ref = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=["user", "client_ref"], name="unique_notification_client_ref"),
        ]

    @classmethod
    def prune(cls, user=None):
        """Deletes notifications older than KEEP_DAYS (for one user, or everyone)."""
        qs = cls.objects.filter(created_at__lt=timezone.now() - timedelta(days=cls.KEEP_DAYS))
        if user is not None:
            qs = qs.filter(user=user)
        return qs.delete()[0]

    def __str__(self):
        return f"Notification for {self.user.username}: {self.title}"
