from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags


def _money(symbol, value):
    value = float(value or 0)
    text = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return f"{symbol}{text}"


def reminder_for(user, today):
    """Title and message for [user]: today's total when something was logged, a nudge
    otherwise."""
    from accounts.models import UserProfile
    from transactions.models import Transaction

    profile, _ = UserProfile.objects.get_or_create(user=user)
    symbol = profile.get_currency_symbol()
    spent = Transaction.objects.filter(user=user, type="expense", date__date=today).aggregate(
        total=Sum("amount"), n=Count("id")
    )
    if spent["n"]:
        entries = "entry" if spent["n"] == 1 else "entries"
        return (
            f"Today: {_money(symbol, spent['total'])} spent",
            f"{spent['n']} {entries} logged so far. Anything else to add? Tap to log it.",
        )
    return (
        "Log today's expenses",
        "You haven't added anything today. It takes 5 seconds to keep your budget on track.",
    )


class Command(BaseCommand):
    help = "Send the daily reminder: saved to each user's in-app notifications, pushed to their phone, emailed if no phone."

    def handle(self, *args, **options):
        from accounts.models import Notification
        from accounts.notify import notify

        users = User.objects.filter(is_active=True, userprofile__email_reminders=True)
        if not users.exists():
            self.stdout.write(self.style.WARNING("No users matched the criteria to send reminders to."))
            return

        today = timezone.localdate()
        recent = timezone.now() - timedelta(minutes=60)
        sent_push = sent_email = skipped = 0

        for user in users:
            # The scheduler and a manual run must not remind twice.
            if Notification.objects.filter(
                user=user, data__kind="daily_reminder", created_at__gte=recent
            ).exists():
                skipped += 1
                continue

            title, message = reminder_for(user, today)
            pushed = notify(user, title, message, data={"action": "open_dashboard", "kind": "daily_reminder"})
            if pushed:
                sent_push += 1
                self.stdout.write(f"Sent push notification to {user.username}")
                continue

            if user.email:
                html_message = render_to_string("accounts/email/daily_reminder.html", {"user": user})
                try:
                    send_mail(
                        "Time to update your Espere expenses!",
                        strip_tags(html_message),
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        html_message=html_message,
                        fail_silently=True,
                    )
                    sent_email += 1
                    self.stdout.write(f"Sent email reminder to {user.email}")
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Failed to send email to {user.email}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Sent {sent_push} push notifications and {sent_email} reminder emails ({skipped} already reminded)."
        ))
