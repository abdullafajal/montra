import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import Notification
from api.authentication import APIToken


class AppNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", "u@example.com", "pw")
        token = APIToken.generate_token(self.user)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {getattr(token, 'key', token)}"}

    def post(self, items):
        return self.client.post("/api/notifications/", data=json.dumps({"notifications": items}),
                                content_type="application/json", **self.auth)

    def test_app_notifications_are_saved_once_with_their_time(self):
        at = (timezone.now() - timedelta(days=2)).isoformat()
        item = {"client_ref": "local:-100", "title": "Daily reminder", "message": "Add today's spends",
                "data": {"kind": "reminder"}, "is_read": False, "created_at": at}
        r = self.post([item])
        self.assertEqual(r.status_code, 200)
        saved = r.json()["notifications"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["client_ref"], "local:-100")
        # Sent again (the app retries): still one, and read on the phone carries over.
        self.post([{**item, "is_read": True}])
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        n = Notification.objects.get(user=self.user)
        self.assertTrue(n.is_read)
        self.assertLess(n.created_at, timezone.now() - timedelta(days=1))
        listed = self.client.get("/api/notifications/", **self.auth).json()["notifications"]
        self.assertEqual(listed[0]["client_ref"], "local:-100")

    def test_older_than_90_days_are_removed(self):
        old = Notification.objects.create(user=self.user, title="old", message="")
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=91))
        Notification.objects.create(user=self.user, title="new", message="")
        listed = self.client.get("/api/notifications/", **self.auth).json()["notifications"]
        self.assertEqual([n["title"] for n in listed], ["new"])
        # And the app can't save one that would be removed straight away.
        r = self.post([{"client_ref": "x", "title": "t", "created_at": (timezone.now() - timedelta(days=100)).isoformat()}])
        self.assertEqual(r.json()["notifications"], [])
