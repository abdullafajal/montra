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
        from accounts.models import DeviceToken
        from config.firebase import send_push_notification

        # Find all active users who have email_reminders enabled
        # (Renamed logically to 'reminders enabled' though model field is email_reminders)
        users = User.objects.filter(
            is_active=True, 
            userprofile__email_reminders=True
        )

        if not users.exists():
            self.stdout.write(self.style.WARNING("No users matched the criteria to send reminders to."))
            return

        subject = "Time to update your Espere expenses!"
        push_body = "Don't forget to log your expenses for today to keep your budget on track!"
        sent_email_count = 0
        sent_push_count = 0

        for user in users:
            # 1. Try pushing notification first if user has app tokens
            tokens = DeviceToken.objects.filter(user=user)
            pushed = False
            
            if tokens.exists():
                for dt in tokens:
                    success = send_push_notification(
                        token=dt.token,
                        title=subject,
                        body=push_body,
                        data={"action": "open_dashboard"}
                    )
                    if success:
                        pushed = True
                
                if pushed:
                    sent_push_count += 1
                    self.stdout.write(f"Sent push notification to {user.username}")
                    continue # Skip email if pushed successfully

            # 2. Fallback to email if not pushed and user has an email
            if user.email:
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
                    sent_email_count += 1
                    self.stdout.write(f"Sent email reminder to {user.email}")
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Failed to send email to {user.email}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Successfully sent {sent_push_count} push notifications and {sent_email_count} reminder emails."
        ))
