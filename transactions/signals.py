"""Signals for cache invalidation."""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Transaction, Category, Budget, SavingsGoal
from core.utils.cache import invalidate_user_cache


@receiver([post_save, post_delete], sender=Transaction)
@receiver([post_save, post_delete], sender=Category)
@receiver([post_save, post_delete], sender=Budget)
@receiver([post_save, post_delete], sender=SavingsGoal)
def invalidate_cache_on_change(sender, instance, **kwargs):
    """Invalidate the user's cache whenever relevant models change."""
    if hasattr(instance, 'user') and instance.user:
        invalidate_user_cache(instance.user.id)
