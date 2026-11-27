"""Removes notifications older than 90 days for every user.

The app's list call already does this for the user asking, so this is only needed to
clean up after people who stopped opening the app. Can run as a daily scheduled task:
    python manage.py prune_notifications
"""
from django.core.management.base import BaseCommand

from accounts.models import Notification


class Command(BaseCommand):
    help = "Delete notifications older than 90 days."

    def handle(self, *args, **options):
        removed = Notification.prune()
        self.stdout.write(f"Removed {removed} old notifications.")
