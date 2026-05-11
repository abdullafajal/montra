"""
Custom token-based authentication for the Espere API.
Uses Django's built-in Token model pattern without DRF dependency.
"""
import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class APIToken(models.Model):
    """Simple token model for API authentication."""
    key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"

    def __str__(self):
        return f"Token for {self.user.username}"

    @classmethod
    def generate_token(cls, user):
        """Create a new token for the given user, removing old ones."""
        cls.objects.filter(user=user).delete()
        key = secrets.token_hex(32)
        return cls.objects.create(user=user, key=key)

    @classmethod
    def get_user_from_token(cls, key):
        """Return the user for a valid token, or None."""
        try:
            token = cls.objects.select_related("user").get(key=key)
            token.last_used = timezone.now()
            token.save(update_fields=["last_used"])
            return token.user
        except cls.DoesNotExist:
            return None
