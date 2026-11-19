"""One place to notify a user: saves the message to their in-app inbox
(``Notification``) and sends it as a push to every device they use."""

from config.firebase import send_push_notification

from .models import DeviceToken, Notification


def notify(user, title, message, data=None, push=True):
    """Saves the notification and pushes it. Returns True if at least one push went out."""
    data = {k: str(v) for k, v in (data or {}).items()}
    note = Notification.objects.create(user=user, title=title, message=message, data=data)
    if not push:
        return False
    pushed = False
    for dt in DeviceToken.objects.filter(user=user):
        if send_push_notification(
            token=dt.token,
            title=title,
            body=message,
            data={**data, "notification_id": str(note.id)},
        ):
            pushed = True
    return pushed
