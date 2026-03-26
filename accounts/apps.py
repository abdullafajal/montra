from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        import accounts.signals  # noqa: F401
        
        import sys
        import os
        
        # Check if we are running as a server (WSGI) or runserver, 
        # and not a management command like migrate or createsuperuser
        is_server = False
        if 'manage.py' in sys.argv:
            if 'runserver' in sys.argv:
                if os.environ.get('RUN_MAIN') == 'true':
                    is_server = True
        else:
            # We are likely running under WSGI/production
            is_server = True
            
        if is_server:
            from .scheduler import start_auto_reminders
            start_auto_reminders()
