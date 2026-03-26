import threading
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = "Send daily reminder emails to users to add their expenses."

    def handle(self, *args, **options):
        # Find all active users who have email_reminders enabled and an email address
        users = User.objects.filter(
            is_active=True, 
            userprofile__email_reminders=True
        ).exclude(email="")

        if not users.exists():
            self.stdout.write(self.style.WARNING("No users matched the criteria to send reminders to."))
            return

        subject = "Time to update your Montra expenses!"
        sent_count = 0

        for user in users:
            context = {"user": user}
            html_message = render_to_string("accounts/email/daily_reminder.html", context)
            plain_message = strip_tags(html_message)
            
            try:
                send_mail(
                    subject,
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    html_message=html_message,
                    fail_silently=True,
                )
                sent_count += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to send email to {user.email}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully sent {sent_count} reminder emails."))
