import json
import random
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.signing import Signer, BadSignature
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from .models import ContactMessage, AppVersion
from accounts.models import DeviceToken
from config.firebase import send_push_notification

def assetlinks_view(request):
    """Serve the assetlinks.json file for Android App Links."""
    data = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": "com.example.espere_app",
            "sha256_cert_fingerprints": [
                # TODO: Replace with the actual SHA-256 fingerprint from Play Console / Keystore
                "FA:C6:17:45:D2:2C:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34"
            ]
        }
    }]
    return JsonResponse(data, safe=False)

def add_cors(response):
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
    return response

@method_decorator(csrf_exempt, name='dispatch')
class ContactCaptchaAPIView(View):
    def options(self, request, *args, **kwargs):
        return add_cors(JsonResponse({}))

    def get(self, request):
        num1 = random.randint(1, 10)
        num2 = random.randint(1, 10)
        answer = str(num1 + num2)
        question = f"{num1} + {num2} = ?"
        signer = Signer()
        token = signer.sign(answer)
        return add_cors(JsonResponse({"question": question, "token": token}))

@method_decorator(csrf_exempt, name='dispatch')
class ContactSubmitAPIView(View):
    def options(self, request, *args, **kwargs):
        return add_cors(JsonResponse({}))

    def post(self, request):
        try:
            data = json.loads(request.body)
            name = data.get('name', '').strip()
            email = data.get('email', '').strip()
            msg_type = data.get('type', 'support').strip()
            message = data.get('message', '').strip()
            captcha_answer = str(data.get('captcha_answer', '')).strip()
            captcha_token = data.get('captcha_token', '').strip()

            if not all([name, email, message, captcha_answer, captcha_token]):
                return add_cors(JsonResponse({"error": "All fields are required."}, status=400))

            # Verify captcha
            signer = Signer()
            try:
                original = signer.unsign(captcha_token)
                if original != captcha_answer:
                    return add_cors(JsonResponse({"error": "Incorrect captcha answer."}, status=400))
            except BadSignature:
                return add_cors(JsonResponse({"error": "Invalid captcha token."}, status=400))

            # Save message
            contact_msg = ContactMessage.objects.create(
                name=name,
                email=email,
                type=msg_type,
                message=message
            )

            # Notify superadmins
            superadmins = User.objects.filter(is_superuser=True)
            notified_via_push = False
            
            for admin in superadmins:
                devices = DeviceToken.objects.filter(user=admin)
                if devices.exists():
                    for device in devices:
                        title = f"New {contact_msg.get_type_display()}"
                        body = f"From: {name}\n{message[:100]}..."
                        if send_push_notification(device.token, title, body):
                            notified_via_push = True

            if not notified_via_push and superadmins.exists():
                admin_emails = [admin.email for admin in superadmins if admin.email]
                if admin_emails:
                    subject = f"New {contact_msg.get_type_display()} from {name}"
                    email_body = f"Name: {name}\nEmail: {email}\nType: {contact_msg.get_type_display()}\n\nMessage:\n{message}"
                    send_mail(
                        subject,
                        email_body,
                        settings.DEFAULT_FROM_EMAIL,
                        admin_emails,
                        fail_silently=True,
                    )

            return add_cors(JsonResponse({"status": "success", "message": "Your message has been sent successfully!"}))
        except json.JSONDecodeError:
            return add_cors(JsonResponse({"error": "Invalid JSON."}, status=400))
        except Exception as e:
            return add_cors(JsonResponse({"error": str(e)}, status=500))

@method_decorator(csrf_exempt, name='dispatch')
class AppVersionAPIView(View):
    def options(self, request, *args, **kwargs):
        return add_cors(JsonResponse({}))

    def get(self, request):
        version = AppVersion.objects.filter(is_active=True).order_by('-version_code').first()
        if not version:
            return add_cors(JsonResponse({
                "version_code": 0,
                "version_name": "1.0.0",
                "is_required": False,
                "release_notes": "Bug fixes and performance improvements.",
                "update_url": "https://espere.in/espere.apk"
            }))
        
        return add_cors(JsonResponse({
            "version_code": version.version_code,
            "version_name": version.version_name,
            "is_required": version.is_required,
            "release_notes": version.release_notes,
            "update_url": version.update_url
        }))
