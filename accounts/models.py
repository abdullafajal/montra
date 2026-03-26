"""Accounts models — UserProfile for preferences."""
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


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
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="light")
    email_reminders = models.BooleanField(default=True, help_text="Receive daily reminders to log expenses.")
    created_at = models.DateTimeField(auto_now_add=True)

    def get_currency_symbol(self):
        return self.CURRENCY_SYMBOLS.get(self.currency, "$")

    def __str__(self):
        return f"{self.user.username}'s Profile"


class EmailVerificationToken(models.Model):
    """One-time token for verifying a user's email address."""
    MAX_ATTEMPTS = 3
    COOLDOWN_HOURS = 24

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="verification_token")
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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
