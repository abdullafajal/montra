import os
import firebase_admin
from firebase_admin import credentials, messaging

def get_firebase_app():
    if not firebase_admin._apps:
        # Look for a service account file
        cred_path = os.path.join(os.path.dirname(__file__), "firebase-adminsdk.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            return firebase_admin.initialize_app(cred)
        else:
            return None
    return firebase_admin.get_app()

def send_push_notification(token, title, body, data=None):
    app = get_firebase_app()
    if not app:
        print("[DEBUG FCM] No firebase-adminsdk.json found, skipping push.")
        return False
        
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=token,
        )
        response = messaging.send(message)
        print(f"[DEBUG FCM] Successfully sent message: {response}")
        return True
    except Exception as e:
        print(f"[DEBUG FCM] Failed to send push: {e}")
        return False
