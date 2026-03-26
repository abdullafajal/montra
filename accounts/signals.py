"""Auto-create UserProfile on User creation."""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile
from core.utils.cache import invalidate_user_cache


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=UserProfile)
def invalidate_cache_on_profile_change(sender, instance, **kwargs):
    """Invalidate the user's cache whenever their profile changes."""
    if hasattr(instance, 'user') and instance.user:
        invalidate_user_cache(instance.user.id)
