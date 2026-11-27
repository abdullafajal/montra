"""
API views for Espere — all JSON endpoints consumed by the Flutter app.

No DRF dependency — uses plain Django views with JSON responses.
"""
import json
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django.conf import settings
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from accounts.models import UserProfile
from transactions.models import Transaction, Category, Budget, SavingsGoal
from .authentication import APIToken
from .decorators import api_login_required, parse_json_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_profile_data(user):
    """Serialize user + profile into a dict."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    avatar_url = ""
    if profile.avatar:
        avatar_url = profile.avatar.url
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "avatar": avatar_url,
        "currency": profile.currency,
        "currency_symbol": profile.get_currency_symbol(),
        "theme": profile.theme,
        "email_reminders": profile.email_reminders,
    }


def _transaction_to_dict(txn, currency_symbol="₹"):
    """Serialize a Transaction instance."""
    return {
        "id": txn.id,
        "amount": str(txn.amount),
        "type": txn.type,
        "category": {
            "id": txn.category_id,
            "name": txn.category.name if txn.category else "Other",
            "icon": txn.category.icon if txn.category else "category",
            "color": txn.category.color if txn.category else "#C8E64A",
        },
        "date": txn.date.isoformat(),
        "payment_method": txn.payment_method,
        "payment_method_display": txn.get_payment_method_display(),
        "notes": txn.notes,
    }


def _saving_goal_to_dict(g):
    """Serialize a SavingsGoal instance."""
    return {
        "id": g.id,
        "name": g.name,
        "target_amount": str(g.target_amount),
        "current_amount": str(g.current_amount),
        "icon": g.icon,
        "color": g.color,
        "deadline": g.deadline.isoformat() if g.deadline else None,
        "is_completed": g.is_completed,
        "percentage": g.get_percentage(),
        "remaining": str(g.get_remaining()),
        "history": [
            {
                "id": t.id,
                "amount": str(t.amount),
                "notes": t.notes,
                "date": t.date.isoformat(),
            }
            for t in g.history.all()[:20]
        ]
    }


def _category_to_dict(cat):
    """Serialize a Category instance."""
    return {
        "id": cat.id,
        "name": cat.name,
        "icon": cat.icon,
        "color": cat.color,
        "is_system": cat.is_system,
        "type": cat.type,
    }


def _get_greeting():
    """Return time-based greeting."""
    hour = timezone.localtime().hour
    if 5 <= hour < 12:
        return "Morning"
    elif 12 <= hour < 17:
        return "Afternoon"
    elif 17 <= hour < 21:
        return "Evening"
    return "Night"


def _parse_api_datetime(value):
    """Parse string to aware datetime, or return timezone.now() as fallback."""
    if not value:
        return timezone.now()

    if isinstance(value, timezone.datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value)
        return value

    # Try parsing as full datetime
    dt = parse_datetime(str(value))
    if dt:
        if timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt

    # Try parsing as date only (YYYY-MM-DD)
    d = parse_date(str(value))
    if d:
        dt = datetime.combine(d, datetime.min.time())
        return timezone.make_aware(dt)

    return timezone.now()


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class LoginAPIView(View):
    """POST /api/auth/login/ — returns token on success."""

    def post(self, request):
        data = parse_json_body(request)
        username = data.get("username", "").strip()
        password = data.get("password", "")

        if not username or not password:
            return JsonResponse(
                {"error": "Username and password are required."},
                status=400,
            )

        # Support login with email
        user = authenticate(request, username=username, password=password)
        if user is None:
            return JsonResponse(
                {"error": "Invalid credentials."},
                status=401,
            )

        if not user.is_active:
            return JsonResponse(
                {"error": "Account not verified. Please check your email."},
                status=403,
            )

        token = APIToken.generate_token(user)
        return JsonResponse({
            "token": token.key,
            "user": _user_profile_data(user),
        })


@method_decorator(csrf_exempt, name="dispatch")
class GoogleLoginAPIView(View):
    """
    POST /api/auth/google/
    Expects JSON: {"id_token": "..."}
    """
    def post(self, request):
        data = parse_json_body(request)
        token = data.get("id_token")
        
        if not token:
            return JsonResponse({"error": "id_token is required."}, status=400)
            
        try:
            # Note: client_id is not strictly verified here if we allow multiple clients (Android, iOS)
            # but we can pass the Web Client ID if we have it.
            # For flexibility across multiple client IDs, we verify without a specific audience,
            # or verify the issuer first.
            idinfo = google_id_token.verify_oauth2_token(
                token, google_requests.Request()
            )

            # Check issuer
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Wrong issuer.')

            # We can optionally verify idinfo['aud'] matches our client IDs here
            
            email = idinfo.get("email")
            first_name = idinfo.get("given_name", "")
            last_name = idinfo.get("family_name", "")
            
            if not email:
                return JsonResponse({"error": "Email not provided by Google."}, status=400)
                
            # Find or create user
            # We search by email to ensure we catch users who signed up manually with a different username
            user, created = User.objects.get_or_create(email=email, defaults={
                'username': email,
                'first_name': first_name,
                'last_name': last_name
            })
            
            # Generate APIToken
            api_token = APIToken.generate_token(user)
            
            return JsonResponse({
                "token": api_token.key,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_new_user": created
            })
            
        except ValueError as e:
            # Invalid token
            return JsonResponse({"error": f"Invalid Google token: {str(e)}"}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class LogoutAPIView(View):
    """POST /api/auth/logout/ — deletes the current session token."""

    @method_decorator(api_login_required)
    def post(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        token_key = auth_header[7:].strip()
        APIToken.objects.filter(key=token_key).delete()
        return JsonResponse({"message": "Logged out successfully."})


@method_decorator(csrf_exempt, name="dispatch")
class DeviceTokenAPIView(View):
    """POST /api/devices/register/ — registers FCM device token."""

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        token = data.get("token")
        if not token:
            return JsonResponse({"error": "Token is required."}, status=400)
            
        from accounts.models import DeviceToken
        # Use update_or_create to avoid IntegrityError if token already exists
        DeviceToken.objects.update_or_create(
            token=token,
            defaults={'user': request.api_user}
        )
        return JsonResponse({"message": "Token registered successfully."})


@method_decorator(csrf_exempt, name="dispatch")
class RegisterAPIView(View):
    """POST /api/auth/register/ — creates user, returns token."""

    def post(self, request):
        data = parse_json_body(request)
        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "")
        password2 = data.get("password2", "")

        errors = {}
        if not username:
            errors["username"] = "Username is required."
        if not email:
            errors["email"] = "Email is required."
        if not password:
            errors["password"] = "Password is required."
        if password != password2:
            errors["password2"] = "Passwords do not match."
        if User.objects.filter(username__iexact=username).exists():
            errors["username"] = "Username already taken."
        if User.objects.filter(email__iexact=email).exists():
            errors["email"] = "Email already registered."

        # Email validation
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_email(email)
        except DjangoValidationError:
            errors["email"] = "Enter a valid email address."

        if errors:
            return JsonResponse({"errors": errors}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=False, # Enforce email verification
        )
        UserProfile.objects.get_or_create(user=user)
        
        # Send verification email
        from accounts.models import EmailVerificationToken
        from accounts.views import _send_verification_email
        token = EmailVerificationToken.objects.create(user=user)
        _send_verification_email(request, user, token)

        return JsonResponse({
            "message": "Registration successful. Please verify your email to log in.",
            "email": email
        }, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class VerifyOTPAPIView(View):
    """POST /api/auth/verify-otp/ — verifies email using 6-digit OTP."""

    def post(self, request):
        data = parse_json_body(request)
        email = data.get("email", "").strip()
        otp = data.get("otp", "").strip()

        if not email or not otp:
            return JsonResponse({"error": "Email and OTP are required."}, status=400)

        from accounts.models import EmailVerificationToken
        try:
            token_obj = EmailVerificationToken.objects.get(user__email__iexact=email, token=otp)

            user = token_obj.user
            user.is_active = True
            user.save()
            token_obj.delete()

            # Process pending split group invitations
            try:
                from split_expense.services import process_external_invite_signup
                process_external_invite_signup(user)
            except Exception as e:
                print(f"Error processing invitations: {e}")

            # Auto-login after successful verification
            from .authentication import APIToken
            api_token = APIToken.generate_token(user)
            return JsonResponse({
                "message": "Email verified successfully.",
                "token": api_token.key,
                "user": _user_profile_data(user),
            })
        except EmailVerificationToken.DoesNotExist:
            return JsonResponse({"error": "Invalid or expired OTP."}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class ResendOTPAPIView(View):
    """POST /api/auth/resend-otp/ — resends email using 6-digit OTP."""

    def post(self, request):
        data = parse_json_body(request)
        email = data.get("email", "").strip()

        if not email:
            return JsonResponse({"error": "Email is required."}, status=400)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Prevent email enumeration
            return JsonResponse({"message": "If the email is registered, a new OTP has been sent."}, status=200)

        if user.is_active:
            return JsonResponse({"error": "Email is already verified."}, status=400)

        from accounts.models import EmailVerificationToken
        from accounts.views import _send_verification_email

        # Delete old tokens
        EmailVerificationToken.objects.filter(user=user).delete()

        # Create and send new token
        token = EmailVerificationToken.objects.create(user=user)
        _send_verification_email(request, user, token)

        return JsonResponse({
            "message": "If the email is registered, a new OTP has been sent."
        }, status=200)

@method_decorator(csrf_exempt, name="dispatch")
class ProfileAPIView(View):
    """GET/PUT /api/auth/profile/ — get or update profile."""

    @method_decorator(api_login_required)
    def get(self, request):
        return JsonResponse({"user": _user_profile_data(request.api_user)})

    @method_decorator(api_login_required)
    def put(self, request):
        data = parse_json_body(request)
        user = request.api_user
        profile, _ = UserProfile.objects.get_or_create(user=user)

        # Update user fields
        if "first_name" in data:
            user.first_name = data["first_name"]
        if "last_name" in data:
            user.last_name = data["last_name"]
        if "email" in data:
            user.email = data["email"]
        user.save()

        # Update profile fields
        if "currency" in data:
            profile.currency = data["currency"]
        if "theme" in data:
            profile.theme = data["theme"]
        if "email_reminders" in data:
            profile.email_reminders = data["email_reminders"]
        profile.save()

        return JsonResponse({"user": _user_profile_data(user)})
        
@method_decorator(csrf_exempt, name="dispatch")
class ChangePasswordAPIView(View):
    """POST /api/auth/password/change/ — change user password."""

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user
        
        old_password = data.get("old_password")
        new_password = data.get("new_password")
        
        if not old_password or not new_password:
            return JsonResponse({"error": "Old and new passwords are required."}, status=400)
            
        if not user.check_password(old_password):
            return JsonResponse({"error": "Incorrect old password."}, status=400)
            
        user.set_password(new_password)
        user.save()
        return JsonResponse({"message": "Password changed successfully."})

@method_decorator(csrf_exempt, name="dispatch")
class AvatarUploadAPIView(View):
    """POST /api/auth/profile/avatar/ — upload avatar."""

    @method_decorator(api_login_required)
    def post(self, request):
        if 'image' not in request.FILES:
            return JsonResponse({"error": "No image file provided."}, status=400)
            
        image = request.FILES['image']
        user = request.api_user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        
        # Delete old avatar if exists
        if profile.avatar:
            try:
                import os
                if os.path.isfile(profile.avatar.path):
                    os.remove(profile.avatar.path)
            except Exception:
                pass
                
        profile.avatar.save(image.name, image, save=True)
        return JsonResponse({"user": _user_profile_data(user)})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class DashboardAPIView(View):
    """GET /api/dashboard/ — aggregated dashboard data.

    ``?month=YYYY-MM`` shows that month (default: this month; future months fall back to
    this month). ``avg_daily`` is the month's spending divided by the days counted: days
    so far for this month, every day for a past month.
    """

    @method_decorator(api_login_required)
    def get(self, request):
        import calendar

        user = request.api_user
        today = timezone.localdate()
        this_month = today.replace(day=1)
        sel = this_month
        month_param = request.GET.get("month", "").strip()
        if month_param:
            try:
                y, m = (int(x) for x in month_param.split("-")[:2])
                sel = date(y, m, 1)
            except (ValueError, TypeError):
                return JsonResponse({"error": "month must look like 2026-11."}, status=400)
        if sel > this_month:
            sel = this_month
        is_current = sel == this_month
        days_in_month = calendar.monthrange(sel.year, sel.month)[1]
        days_counted = today.day if is_current else days_in_month

        month_txns = Transaction.objects.filter(user=user, date__year=sel.year, date__month=sel.month)
        income = month_txns.filter(type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        expenses = month_txns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        avg_daily = (expenses / days_counted) if days_counted else Decimal("0")

        # Spending per day of the month, and per week (1–7, 8–14, …).
        daily_values = [0.0] * days_in_month
        per_day = (
            month_txns.filter(type="expense")
            .values("date__date")
            .annotate(t=Sum("amount"))
        )
        for row in per_day:
            d = row["date__date"]
            if d and d.month == sel.month:
                daily_values[d.day - 1] += float(row["t"] or 0)
        week_labels, week_values = [], []
        for start in range(1, days_in_month + 1, 7):
            end = min(start + 6, days_in_month)
            week_labels.append(f"{start}–{end}")
            week_values.append(round(sum(daily_values[start - 1:end]), 2))

        # All-time balance
        all_income = Transaction.objects.filter(user=user, type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        all_expenses = Transaction.objects.filter(user=user, type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        total_balance = all_income - all_expenses

        # Recent transactions: the latest overall for this month, that month's otherwise.
        recent_qs = Transaction.objects.filter(user=user) if is_current else month_txns
        recent = recent_qs.select_related("category").order_by("-date", "-id")[:5]
        profile, _ = UserProfile.objects.get_or_create(user=user)
        currency_symbol = profile.get_currency_symbol()

        # Chart data: expenses by category
        cat_data = (
            month_txns.filter(type="expense")
            .values("category__name", "category__color")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:8]
        )
        pie_labels = [d["category__name"] or "Other" for d in cat_data]
        pie_values = [float(d["total"]) for d in cat_data]
        pie_colors = [d["category__color"] or "#6366f1" for d in cat_data]

        # Chart data: income vs expense for the 6 months up to the selected one
        bar_labels, bar_income, bar_expense = [], [], []
        for i in range(5, -1, -1):
            idx = sel.year * 12 + (sel.month - 1) - i
            y, m = divmod(idx, 12)
            m += 1
            bar_labels.append(date(y, m, 1).strftime("%b"))
            mtxns = Transaction.objects.filter(user=user, date__year=y, date__month=m)
            bar_income.append(float(mtxns.filter(type="income").aggregate(t=Sum("amount"))["t"] or 0))
            bar_expense.append(float(mtxns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or 0))

        # Chart data: 30-day spending trend (one query)
        first_day = today - timedelta(days=29)
        trend = dict(
            Transaction.objects.filter(user=user, type="expense", date__date__gte=first_day, date__date__lte=today)
            .values_list("date__date")
            .annotate(t=Sum("amount"))
        )
        line_labels, line_values = [], []
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            line_labels.append(d.strftime("%d"))
            line_values.append(float(trend.get(d) or 0))

        # Auto-create / carry forward budgets for the current month if none exist
        if is_current:
            from transactions.services import ensure_current_month_budgets
            ensure_current_month_budgets(user, today)

        # Budget warnings and overall monthly budget
        month_budgets = Budget.objects.filter(user=user, month__year=sel.year, month__month=sel.month).select_related("category")
        budget_warnings = []
        monthly_budget_limit = Decimal("0")
        monthly_budget_spent = Decimal("0")

        for b in month_budgets:
            spent = b.get_spent()
            monthly_budget_limit += b.amount
            monthly_budget_spent += spent
            if spent > b.amount:
                budget_warnings.append({
                    "category": b.category.name,
                    "icon": b.category.icon,
                    "color": b.category.color
                })

        # A whole-month budget, when set, is the month's limit instead of the categories' sum.
        overall_profile, _ = UserProfile.objects.get_or_create(user=user)
        if overall_profile.monthly_budget > 0:
            monthly_budget_limit = overall_profile.monthly_budget

        # Insights
        insights = _generate_insights(user, today if is_current else sel, income, expenses)

        from split_expense.models import Friendship
        total_friends = Friendship.objects.filter(user=user).count()

        from accounts.models import Notification
        unread = Notification.objects.filter(user=user, is_read=False).count()

        return JsonResponse({
            "month": sel.strftime("%Y-%m"),
            "is_current_month": is_current,
            "greeting": _get_greeting(),
            "user": _user_profile_data(user),
            "total_balance": str(total_balance),
            "monthly_income": str(income),
            "monthly_expenses": str(expenses),
            "monthly_savings": str(income - expenses),
            "avg_daily": str(avg_daily.quantize(Decimal("0.01"))),
            "days_counted": days_counted,
            "daily_values": daily_values,
            "week_labels": week_labels,
            "week_values": week_values,
            "unread_notifications": unread,
            "total_friends": total_friends,
            "monthly_budget_limit": str(monthly_budget_limit),
            "monthly_budget_spent": str(monthly_budget_spent),
            "currency_symbol": currency_symbol,
            "recent_transactions": [_transaction_to_dict(t, currency_symbol) for t in recent],
            "pie_labels": pie_labels,
            "pie_values": pie_values,
            "pie_colors": pie_colors,
            "bar_labels": bar_labels,
            "bar_income": bar_income,
            "bar_expense": bar_expense,
            "line_labels": line_labels,
            "line_values": line_values,
            "budget_warnings": budget_warnings,
            "insights": insights,
        })


def _notification_json(n):
    return {
        "id": n.id,
        "title": n.title,
        "message": n.message,
        "data": n.data or {},
        "is_read": n.is_read,
        "client_ref": n.client_ref,
        "created_at": n.created_at.isoformat(),
    }


@method_decorator(csrf_exempt, name="dispatch")
class NotificationListAPIView(View):
    """GET /api/notifications/ — the user's notifications, newest first.

    ``?limit=`` (default 50, max 100). Returns ``notifications`` and ``unread_count``.
    Notifications older than 90 days are removed first.

    POST /api/notifications/ — saves notifications the app made itself (daily reminders,
    budget alerts): ``{"notifications": [{"client_ref", "title", "message", "data",
    "is_read", "created_at"}, ...]}``. Saving one with a ``client_ref`` already saved
    returns the saved one, so the app can safely send the same list again. Returns the
    saved ``notifications``.
    """

    @method_decorator(api_login_required)
    def get(self, request):
        from accounts.models import Notification

        try:
            limit = max(1, min(100, int(request.GET.get("limit", 50))))
        except ValueError:
            limit = 50
        Notification.prune(request.api_user)
        qs = Notification.objects.filter(user=request.api_user)
        return JsonResponse({
            "notifications": [_notification_json(n) for n in qs[:limit]],
            "unread_count": qs.filter(is_read=False).count(),
        })

    @method_decorator(api_login_required)
    def post(self, request):
        from accounts.models import Notification
        from django.utils.dateparse import parse_datetime

        data = parse_json_body(request)
        incoming = data.get("notifications")
        if not isinstance(incoming, list):
            return JsonResponse({"error": "Send a list in notifications."}, status=400)
        oldest = timezone.now() - timedelta(days=Notification.KEEP_DAYS)
        saved = []
        for item in incoming[:100]:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("client_ref") or "").strip()[:64]
            title = str(item.get("title") or "").strip()[:255]
            if not ref or not title:
                continue
            created = parse_datetime(str(item.get("created_at") or "")) or timezone.now()
            if timezone.is_naive(created):
                created = timezone.make_aware(created)
            created = min(created, timezone.now())
            if created < oldest:
                continue  # would be removed straight away
            extra = item.get("data") if isinstance(item.get("data"), dict) else {}
            n, made = Notification.objects.get_or_create(
                user=request.api_user,
                client_ref=ref,
                defaults={
                    "title": title,
                    "message": str(item.get("message") or "")[:2000],
                    "data": extra,
                    "is_read": bool(item.get("is_read")),
                    "created_at": created,
                },
            )
            # Read on the phone before it was saved: keep it read.
            if not made and item.get("is_read") and not n.is_read:
                n.is_read = True
                n.save(update_fields=["is_read"])
            saved.append(_notification_json(n))
        return JsonResponse({"notifications": saved})


@method_decorator(csrf_exempt, name="dispatch")
class NotificationReadAPIView(View):
    """POST /api/notifications/read/ — marks ``{"ids": [..]}`` as read, or all of them when
    no ids are sent."""

    @method_decorator(api_login_required)
    def post(self, request):
        from accounts.models import Notification

        data = parse_json_body(request)
        qs = Notification.objects.filter(user=request.api_user, is_read=False)
        ids = data.get("ids")
        if isinstance(ids, list) and ids:
            qs = qs.filter(id__in=[i for i in ids if isinstance(i, int)])
        updated = qs.update(is_read=True)
        return JsonResponse({"updated": updated, "unread_count": Notification.objects.filter(
            user=request.api_user, is_read=False).count()})


@method_decorator(csrf_exempt, name="dispatch")
class NotificationDeleteAPIView(View):
    """DELETE /api/notifications/<id>/ — removes one notification."""

    @method_decorator(api_login_required)
    def delete(self, request, pk):
        from accounts.models import Notification

        deleted, _ = Notification.objects.filter(user=request.api_user, pk=pk).delete()
        if not deleted:
            return JsonResponse({"error": "Not found."}, status=404)
        return JsonResponse({"message": "Deleted."})


@method_decorator(csrf_exempt, name="dispatch")
class ReportAPIView(View):
    """GET /api/reports/ — yearly report data."""

    @method_decorator(api_login_required)
    def get(self, request):
        from reports.views import ReportsView
        user = request.api_user
        today = timezone.localdate()
        year = int(request.GET.get("year", today.year))

        # Re-use the logic from ReportsView but return JSON
        view = ReportsView()
        request.user = user  # Ensure request.user is set for the view
        view.request = request
        ctx = view.get_context_data(year=year)

        return JsonResponse({
            "selected_year": ctx["selected_year"],
            "currency_symbol": user.userprofile.get_currency_symbol() if hasattr(user, 'userprofile') else "$",
            "annual_income": str(ctx["annual_income"]),
            "annual_expenses": str(ctx["annual_expenses"]),
            "annual_net": str(ctx["annual_net"]),
            "monthly_summary": ctx["monthly_summary"],
            "top_categories": ctx["top_categories"],
            "bar_labels": json.loads(ctx["monthly_labels"]),
            "bar_income": json.loads(ctx["monthly_income_data"]),
            "bar_expense": json.loads(ctx["monthly_expense_data"]),
            "pie_labels": json.loads(ctx["cat_labels"]),
            "pie_values": json.loads(ctx["cat_values"]),
            "pie_colors": json.loads(ctx["cat_colors"]),
            "pie_icons": json.loads(ctx["cat_icons"]),
            "savings_trend": json.loads(ctx["savings_data"]),
        })


def _generate_insights(user, today, current_income, current_expenses):
    """Generate smart financial insight messages."""
    insights = []
    prev_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    prev_end = today.replace(day=1) - timedelta(days=1)
    prev_expenses = Transaction.objects.filter(
        user=user, type="expense", date__date__gte=prev_start, date__date__lte=prev_end
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")

    if prev_expenses > 0 and current_expenses > 0:
        change = ((current_expenses - prev_expenses) / prev_expenses) * 100
        if change > 0:
            insights.append(f"You spent {abs(change):.0f}% more than last month.")
        elif change < -5:
            insights.append(f"Great! You spent {abs(change):.0f}% less than last month.")

    if current_income > current_expenses:
        savings_rate = ((current_income - current_expenses) / current_income) * 100
        insights.append(f"Your savings rate this month is {savings_rate:.0f}%.")

    if current_expenses > current_income and current_income > 0:
        insights.append("You're spending more than you earn this month!")

    if not insights:
        insights.append("Start tracking your expenses to get personalized insights!")

    return insights


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class TransactionListAPIView(View):
    """GET /api/transactions/ — list with filters.
       POST /api/transactions/ — create new transaction."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        qs = Transaction.objects.filter(user=user).select_related("category").order_by("-date", "-created_at")

        # Filters
        q = request.GET.get("q", "")
        if q:
            qs = qs.filter(Q(notes__icontains=q) | Q(category__name__icontains=q))

        txn_type = request.GET.get("type", "")
        if txn_type in ("income", "expense"):
            qs = qs.filter(type=txn_type)

        cat_id = request.GET.get("category", "")
        if cat_id:
            qs = qs.filter(category_id=cat_id)

        # Month filter
        month_param = request.GET.get("month", "")
        show_all = request.GET.get("all", "") == "1"
        if not show_all:
            if month_param:
                try:
                    y, m = map(int, month_param.split("-"))
                    qs = qs.filter(date__year=y, date__month=m)
                except ValueError:
                    pass
            else:
                today = timezone.localdate()
                qs = qs.filter(date__year=today.year, date__month=today.month)

        # Calculate statistics
        qs_expenses = qs.filter(type="expense")
        qs_incomes = qs.filter(type="income")
        
        from django.db.models import Sum
        total_spend = qs_expenses.aggregate(t=Sum("amount"))["t"] or Decimal("0")
        total_income = qs_incomes.aggregate(t=Sum("amount"))["t"] or Decimal("0")
        
        today = timezone.localdate()
        # Ensure we filter today's date in local time
        today_spend = qs_expenses.filter(date__year=today.year, date__month=today.month, date__day=today.day).aggregate(t=Sum("amount"))["t"] or Decimal("0")
        
        avg_daily = Decimal("0")
        if show_all:
            earliest = qs_expenses.order_by("date").first()
            if earliest:
                days = (today - timezone.localdate(earliest.date)).days + 1
                avg_daily = total_spend / days if days > 0 else total_spend
        else:
            if month_param:
                try:
                    y, m = map(int, month_param.split("-"))
                    target_month = date(y, m, 1)
                except ValueError:
                    target_month = today.replace(day=1)
            else:
                target_month = today.replace(day=1)
                
            import calendar
            if target_month.year == today.year and target_month.month == today.month:
                days = today.day
                avg_daily = total_spend / days if days > 0 else total_spend
            else:
                _, days_in_month = calendar.monthrange(target_month.year, target_month.month)
                avg_daily = total_spend / days_in_month

        # Pagination
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 50))
        if show_all:
            per_page = 5000  # Emulate fetching all time transactions
        total = qs.count()
        offset = (page - 1) * per_page
        transactions = qs[offset:offset + per_page]

        profile, _ = UserProfile.objects.get_or_create(user=user)
        cs = profile.get_currency_symbol()

        return JsonResponse({
            "transactions": [_transaction_to_dict(t, cs) for t in transactions],
            "currency_symbol": cs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "has_next": offset + per_page < total,
            "total_spend": str(total_spend),
            "total_income": str(total_income),
            "today_spend": str(today_spend),
            "avg_daily": str(avg_daily),
        })

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user

        errors = {}
        amount_str = data.get("amount", "")
        try:
            amount = Decimal(str(amount_str))
            if amount <= 0:
                errors["amount"] = "Amount must be positive."
        except (InvalidOperation, ValueError):
            errors["amount"] = "Invalid amount."

        txn_type = data.get("type", "")
        if txn_type not in ("income", "expense"):
            errors["type"] = "Type must be 'income' or 'expense'."

        category_id = data.get("category_id")
        category = None
        if category_id:
            try:
                category = Category.objects.get(
                    Q(id=category_id) & (Q(is_system=True) | Q(user=user))
                )
            except Category.DoesNotExist:
                errors["category"] = "Invalid category."

        if errors:
            return JsonResponse({"errors": errors}, status=400)

        txn = Transaction.objects.create(
            user=user,
            amount=amount,
            type=txn_type,
            category=category,
            date=_parse_api_datetime(data.get("date")),
            payment_method=data.get("payment_method", "cash"),
            notes=data.get("notes", ""),
        )

        profile, _ = UserProfile.objects.get_or_create(user=user)
        return JsonResponse(
            {"transaction": _transaction_to_dict(txn, profile.get_currency_symbol())},
            status=201,
        )


@method_decorator(csrf_exempt, name="dispatch")
class TransactionDetailAPIView(View):
    """PUT/DELETE /api/transactions/<id>/"""

    @method_decorator(api_login_required)
    def get(self, request, pk):
        try:
            txn = Transaction.objects.select_related("category").get(pk=pk, user=request.api_user)
        except Transaction.DoesNotExist:
            return JsonResponse({"error": "Transaction not found."}, status=404)

        profile, _ = UserProfile.objects.get_or_create(user=request.api_user)
        return JsonResponse({"transaction": _transaction_to_dict(txn, profile.get_currency_symbol())})

    @method_decorator(api_login_required)
    def put(self, request, pk):
        try:
            txn = Transaction.objects.get(pk=pk, user=request.api_user)
        except Transaction.DoesNotExist:
            return JsonResponse({"error": "Transaction not found."}, status=404)

        data = parse_json_body(request)

        if "amount" in data:
            try:
                txn.amount = Decimal(str(data["amount"]))
            except (InvalidOperation, ValueError):
                return JsonResponse({"errors": {"amount": "Invalid amount."}}, status=400)

        if "type" in data and data["type"] in ("income", "expense"):
            txn.type = data["type"]

        if "category_id" in data:
            if not data["category_id"]:
                # No category (shown as "Other"), the same as when creating.
                txn.category = None
            else:
                try:
                    txn.category = Category.objects.get(
                        Q(id=data["category_id"]) & (Q(is_system=True) | Q(user=request.api_user))
                    )
                except Category.DoesNotExist:
                    return JsonResponse({"errors": {"category": "Invalid category."}}, status=400)

        if "date" in data:
            txn.date = _parse_api_datetime(data["date"])
        if "payment_method" in data:
            txn.payment_method = data["payment_method"]
        if "notes" in data:
            txn.notes = data["notes"]

        txn.save()
        profile, _ = UserProfile.objects.get_or_create(user=request.api_user)
        return JsonResponse({"transaction": _transaction_to_dict(txn, profile.get_currency_symbol())})

    @method_decorator(api_login_required)
    def delete(self, request, pk):
        try:
            txn = Transaction.objects.get(pk=pk, user=request.api_user)
        except Transaction.DoesNotExist:
            return JsonResponse({"error": "Transaction not found."}, status=404)

        txn.delete()
        return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class CategoryListAPIView(View):
    """GET /api/categories/ — list system + user categories.
       POST /api/categories/ — create a user category."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        categories = Category.objects.filter(Q(is_system=True) | Q(user=user))
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return JsonResponse({
            "categories": [_category_to_dict(c) for c in categories],
            "currency_symbol": profile.get_currency_symbol()
        })

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Category name is required."}, status=400)

        icon = data.get("icon", "category")
        color = data.get("color", "#C8E64A")

        # Validate color format
        if not color.startswith("#") or len(color) != 7:
            color = "#C8E64A"

        category_type = data.get("type", "expense")
        if category_type not in ["income", "expense"]:
            category_type = "expense"

        category = Category.objects.create(
            name=name,
            icon=icon,
            color=color,
            type=category_type,
            user=user,
            is_system=False,
        )
        return JsonResponse({"category": _category_to_dict(category)}, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class CategoryDetailAPIView(View):
    """DELETE /api/categories/<id>/ — delete a user category."""

    @method_decorator(api_login_required)
    def put(self, request, pk):
        try:
            category = Category.objects.get(pk=pk, user=request.api_user, is_system=False)
        except Category.DoesNotExist:
            return JsonResponse({"error": "Category not found."}, status=404)

        data = parse_json_body(request)
        if "name" in data:
            category.name = data["name"].strip()
        if "icon" in data:
            category.icon = data["icon"]
        if "color" in data:
            category.color = data["color"]
        if "type" in data and data["type"] in ["income", "expense"]:
            category.type = data["type"]
        
        category.save()
        return JsonResponse({"category": _category_to_dict(category)})

    @method_decorator(api_login_required)
    def delete(self, request, pk):
        try:
            category = Category.objects.get(pk=pk, user=request.api_user, is_system=False)
        except Category.DoesNotExist:
            return JsonResponse({"error": "Category not found or cannot be deleted."}, status=404)

        category.delete()
        return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def _budget_to_dict(b):
    return {
        "id": b.id,
        "category": _category_to_dict(b.category),
        "amount": str(b.amount),
        "month": b.month.isoformat(),
        "spent": str(b.get_spent()),
        "percentage": b.get_percentage(),
        "is_exceeded": b.is_exceeded(),
        "repeat": b.repeat,
        "carry_over": b.carry_over,
        "carried": str(b.carried),
    }


def _overall_budget(user, month_date):
    """The whole-month limit (0 = none) and what was spent in that month."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    spent = Transaction.objects.filter(
        user=user, type="expense", date__year=month_date.year, date__month=month_date.month
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return {"amount": str(profile.monthly_budget), "spent": str(spent)}


@method_decorator(csrf_exempt, name="dispatch")
class BudgetListAPIView(View):
    """GET /api/budgets/ — list budgets with spent info."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        budgets = Budget.objects.filter(user=user).select_related("category")
        
        # Add month filter
        month_param = request.GET.get("month", "")
        if month_param:
            try:
                y, m = map(int, month_param.split("-"))
                month_date = date(y, m, 1)
                
                # Auto carry-forward logic using service
                from transactions.services import ensure_current_month_budgets
                ensure_current_month_budgets(user, month_date)
                
                budgets = budgets.filter(month__year=y, month__month=m)
            except ValueError:
                pass
        else:
            # If no month parameter is provided, make sure current month budgets exist
            from transactions.services import ensure_current_month_budgets
            ensure_current_month_budgets(user)

        data = [_budget_to_dict(b) for b in budgets]
        profile, _ = UserProfile.objects.get_or_create(user=user)
        try:
            y, m = map(int, month_param.split("-")) if month_param else (None, None)
            shown = date(y, m, 1) if y else timezone.localdate().replace(day=1)
        except ValueError:
            shown = timezone.localdate().replace(day=1)
        return JsonResponse({
            "budgets": data,
            "overall": _overall_budget(user, shown),
            "currency_symbol": profile.get_currency_symbol()
        })

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user

        try:
            category = Category.objects.get(
                Q(id=data.get("category_id")) & (Q(is_system=True) | Q(user=user))
            )
        except Category.DoesNotExist:
            return JsonResponse({"error": "Invalid category."}, status=400)

        try:
            amount = Decimal(str(data.get("amount", "0")))
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)

        month_str = data.get("month", "")
        month_date = timezone.localdate().replace(day=1)
        if month_str:
            try:
                month_date = datetime.strptime(month_str, "%Y-%m-%d").date().replace(day=1)
            except (ValueError, TypeError):
                pass

        # Setting the amount by hand replaces any carried-over part.
        defaults = {"amount": amount, "carried": Decimal("0")}
        if "repeat" in data:
            defaults["repeat"] = bool(data["repeat"])
        if "carry_over" in data:
            defaults["carry_over"] = bool(data["carry_over"])
        budget, created = Budget.objects.update_or_create(
            user=user, category=category, month=month_date,
            defaults=defaults,
        )
        return JsonResponse({"budget": _budget_to_dict(budget)}, status=201 if created else 200)


@method_decorator(csrf_exempt, name="dispatch")
class OverallBudgetAPIView(View):
    """GET/PUT /api/budgets/overall/ — one spending limit for the whole month (0 = none)."""

    @method_decorator(api_login_required)
    def get(self, request):
        return JsonResponse({"overall": _overall_budget(request.api_user, timezone.localdate().replace(day=1))})

    @method_decorator(api_login_required)
    def put(self, request):
        data = parse_json_body(request)
        try:
            amount = Decimal(str(data.get("amount", "0")))
            if amount < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)
        profile, _ = UserProfile.objects.get_or_create(user=request.api_user)
        profile.monthly_budget = amount
        profile.save(update_fields=["monthly_budget"])
        return JsonResponse({"overall": _overall_budget(request.api_user, timezone.localdate().replace(day=1))})


@method_decorator(csrf_exempt, name="dispatch")
class BudgetDetailAPIView(View):
    """DELETE /api/budgets/<id>/"""

    @method_decorator(api_login_required)
    def delete(self, request, pk):
        try:
            budget = Budget.objects.get(pk=pk, user=request.api_user)
            budget.delete()
            return JsonResponse({"message": "Budget deleted successfully."})
        except Budget.DoesNotExist:
            return JsonResponse({"error": "Budget not found."}, status=404)


# ---------------------------------------------------------------------------
# Savings Goals
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class SavingsListAPIView(View):
    """GET /api/savings/ — list savings goals."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        goals = SavingsGoal.objects.filter(user=user)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return JsonResponse({
            "goals": [_saving_goal_to_dict(g) for g in goals],
            "currency_symbol": profile.get_currency_symbol()
        })

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user

        try:
            target = Decimal(str(data.get("target_amount", "0")))
            current = Decimal(str(data.get("current_amount", "0")))
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)

        goal = SavingsGoal.objects.create(
            user=user,
            name=data.get("name", "My Goal"),
            target_amount=target,
            current_amount=current,
            icon=data.get("icon", "savings"),
            color=data.get("color", "#C8E64A"),
        )
        if data.get("deadline"):
            try:
                from datetime import datetime
                goal.deadline = datetime.strptime(data["deadline"], "%Y-%m-%d").date()
                goal.save()
            except (ValueError, TypeError):
                pass

        return JsonResponse({
            "goal": {
                "id": goal.id,
                "name": goal.name,
                "target_amount": str(goal.target_amount),
                "current_amount": str(goal.current_amount),
                "percentage": goal.get_percentage(),
            }
        }, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class SavingsAddMoneyAPIView(View):
    """POST /api/savings/<id>/add-money/"""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        try:
            goal = SavingsGoal.objects.get(pk=pk, user=request.api_user)
        except SavingsGoal.DoesNotExist:
            return JsonResponse({"error": "Goal not found."}, status=404)

        data = parse_json_body(request)
        try:
            amount = Decimal(str(data.get("amount", "0")))
            notes = data.get("notes", "")
            if amount <= 0:
                return JsonResponse({"error": "Amount must be positive."}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)

        goal.add_money(amount, notes=notes)
        return JsonResponse({
            "goal": _saving_goal_to_dict(goal)
        })


@method_decorator(csrf_exempt, name="dispatch")
class SavingsDetailAPIView(View):
    """GET/PUT/DELETE /api/savings/<id>/"""

    @method_decorator(api_login_required)
    def get(self, request, pk):
        try:
            goal = SavingsGoal.objects.get(pk=pk, user=request.api_user)
        except SavingsGoal.DoesNotExist:
            return JsonResponse({"error": "Goal not found."}, status=404)
        return JsonResponse({"goal": _saving_goal_to_dict(goal)})

    @method_decorator(api_login_required)
    def put(self, request, pk):
        try:
            goal = SavingsGoal.objects.get(pk=pk, user=request.api_user)
        except SavingsGoal.DoesNotExist:
            return JsonResponse({"error": "Goal not found."}, status=404)

        data = parse_json_body(request)
        if "name" in data:
            goal.name = data["name"]
        if "target_amount" in data:
            goal.target_amount = Decimal(str(data["target_amount"]))
        if "current_amount" in data:
            goal.current_amount = Decimal(str(data["current_amount"]))
        if "icon" in data:
            goal.icon = data["icon"]
        if "color" in data:
            goal.color = data["color"]
        if "deadline" in data:
            try:
                goal.deadline = parse_date(data["deadline"])
            except:
                pass
        
        goal.save()
        return JsonResponse({"goal": _saving_goal_to_dict(goal)})

    @method_decorator(api_login_required)
    def delete(self, request, pk):
        try:
            goal = SavingsGoal.objects.get(pk=pk, user=request.api_user)
        except SavingsGoal.DoesNotExist:
            return JsonResponse({"error": "Goal not found."}, status=404)

        goal.delete()
        return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# Split Expense
# ---------------------------------------------------------------------------
from split_expense.models import Group, GroupMember, Expense, ExpenseSplit, Settlement, Friendship, FriendRequest, ExternalFriendInvitation, GroupInvitation
from split_expense.services import create_expense, create_settlement, calculate_simplified_debts

@method_decorator(csrf_exempt, name="dispatch")
class SplitGroupListAPIView(View):
    """GET /api/split/groups/ — list groups.
       POST /api/split/groups/ — create a group."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        memberships = GroupMember.objects.filter(user=user).select_related("group")
        data = []
        for m in memberships:
            data.append({
                "id": m.group.id,
                "name": m.group.name,
                "created_at": m.group.created_at.isoformat(),
                "net_balance": str(m.net_balance),
                "is_accepted": m.is_accepted,
                "total_members": m.group.members.count(),
                "color": m.group.color,
                "icon": m.group.icon,
                "created_by_id": m.group.created_by_id,
            })
        return JsonResponse({"groups": data})

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Group name is required."}, status=400)

        # De-duplication check for offline sync
        local_id = data.get("local_id")
        if local_id:
            existing = Group.objects.filter(created_by=user, local_id=local_id).first()
            if existing:
                return JsonResponse({
                    "group": {
                        "id": existing.id, 
                        "name": existing.name, 
                        "total_members": existing.members.count(),
                        "color": existing.color,
                        "icon": existing.icon
                    },
                    "already_existed": True
                }, status=200)

        color = data.get("color", "#C8E64A")
        icon = data.get("icon", "groups")
        members_can_invite = data.get("members_can_invite", True)
        group = Group.objects.create(
            name=name, created_by=user, local_id=local_id, 
            color=color, icon=icon, members_can_invite=members_can_invite
        )
        GroupMember.objects.create(group=group, user=user, is_accepted=True)

        # Add other members by ID or username
        member_ids = data.get("member_ids", [])
        member_list = data.get("members", [])
        
        # Merge them into a single processing loop
        all_members = list(member_ids) + list(member_list)
        
        for item in all_members:
            try:
                if isinstance(item, int) or (isinstance(item, str) and item.isdigit()):
                    mid = int(item)
                    if mid == user.id: continue
                    member_user = User.objects.get(id=mid)
                else:
                    uname = item.strip()
                    if not uname or uname == user.username:
                        continue
                    member_user = User.objects.get(username=uname)
                
                GroupMember.objects.get_or_create(group=group, user=member_user, defaults={"is_accepted": False})
            except (User.DoesNotExist, AttributeError, ValueError):
                pass

        return JsonResponse({
            "group": {
                "id": group.id,
                "name": group.name,
                "total_members": group.members.count(),
                "color": group.color,
                "icon": group.icon,
            }
        }, status=201)

@method_decorator(csrf_exempt, name="dispatch")
class SplitGroupDetailAPIView(View):
    """GET /api/split/groups/<id>/"""

    @method_decorator(api_login_required)
    def get(self, request, pk):
        user = request.api_user
        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found"}, status=404)
            
        if not membership.is_accepted and membership.group.created_by != user:
            return JsonResponse({
                "error": "Invitation pending",
                "is_pending": True,
                "group": {
                    "id": membership.group.id,
                    "name": membership.group.name,
                    "invited_by": membership.group.created_by.username
                }
            }, status=403)
            
        group = membership.group
        
        # members
        members_data = []
        for gm in GroupMember.objects.filter(group=group).select_related("user", "user__userprofile"):
            u_data = get_user_data(request, gm.user)
            u_data["net_balance"] = str(gm.net_balance)
            u_data["is_accepted"] = gm.is_accepted
            u_data["is_creator"] = gm.user_id == group.created_by_id
            members_data.append(u_data)

        # people invited by email who have not joined the app yet
        pending_invites = [
            {
                "email": inv.email,
                "invited_by": get_user_data(request, inv.invited_by)["display_name"],
                "created_at": inv.created_at.isoformat(),
            }
            for inv in group.email_invitations.select_related("invited_by").order_by("-created_at")
        ]
            
        # expenses
        expenses_data = []
        for ex in Expense.objects.filter(group=group).select_related("paid_by", "created_by").prefetch_related("splits__user").order_by("-date", "-created_at")[:50]:
            splits = []
            for sp in ex.splits.all():
                splits.append({
                    **get_user_data(request, sp.user),
                    "user_id": sp.user.id,
                    "amount": str(sp.amount_owed),
                    "value": str(sp.percentage) if ex.split_type == 'percentage' else str(sp.amount_owed)
                })

            expenses_data.append({
                "id": ex.id,
                "description": ex.description,
                "category": ex.category,
                "amount": str(ex.amount),
                "paid_by": get_user_data(request, ex.paid_by),
                "created_by_id": ex.created_by.id if ex.created_by else ex.paid_by.id,
                "split_type": ex.split_type,
                "date": ex.date.isoformat(),
                "splits": splits,
            })

        # simplified debts
        debts = calculate_simplified_debts(group)
        debts_data = []
        for d in debts:
            debts_data.append({
                "from_user": get_user_data(request, d["from"])["display_name"],
                "from_user_id": d["from"].id,
                "to_user": get_user_data(request, d["to"])["display_name"],
                "to_user_id": d["to"].id,
                "amount": str(d["amount"]),
            })

        # settlements
        settlements_data = []
        for s in Settlement.objects.filter(group=group).select_related("paid_by", "paid_to").order_by("-date")[:20]:
            settlements_data.append({
                "id": s.id,
                "paid_by": get_user_data(request, s.paid_by)["display_name"],
                "paid_to": get_user_data(request, s.paid_to)["display_name"],
                "amount": str(s.amount),
                "date": s.date.isoformat(),
            })

        return JsonResponse({
            "group": {
                "id": group.id,
                "name": group.name,
                "color": group.color,
                "icon": group.icon,
                "created_by_id": group.created_by_id,
                "invite_token": str(group.invite_token),
                "members_can_invite": group.members_can_invite,
                "created_at": group.created_at.isoformat(),
                "my_net_balance": str(membership.net_balance),
                "members": members_data,
                "pending_invites": pending_invites,
                "recent_expenses": expenses_data,
                "simplified_debts": debts_data,
                "settlements": settlements_data,
            }
        })

    @method_decorator(api_login_required)
    def put(self, request, pk):
        user = request.api_user
        try:
            group = Group.objects.get(id=pk, created_by=user)
        except Group.DoesNotExist:
            return JsonResponse({"error": "Group not found or you are not the owner."}, status=403)
            
        data = parse_json_body(request)
        if "name" in data:
            group.name = data["name"].strip()
        if "color" in data:
            group.color = data["color"]
        if "icon" in data:
            group.icon = data["icon"]
        if "members_can_invite" in data:
            group.members_can_invite = data["members_can_invite"]
            
        group.save()
        return JsonResponse({"message": "Group updated successfully."})

    @method_decorator(api_login_required)
    def patch(self, request, pk):
        user = request.api_user
        data = parse_json_body(request)
        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found"}, status=404)
            
        group = membership.group
        if "name" in data: group.name = data["name"]
        if "color" in data: group.color = data["color"]
        if "icon" in data: group.icon = data["icon"]
        group.save()
        
        return JsonResponse({
            "group": {
                "id": group.id,
                "name": group.name,
                "color": group.color,
                "icon": group.icon,
            }
        })

    @method_decorator(api_login_required)
    def delete(self, request, pk):
        user = request.api_user
        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found"}, status=404)
            
        group = membership.group
        # Owner only
        if group.created_by != user:
            return JsonResponse({"error": "Only the group owner can delete the group."}, status=403)
            
        # Check if all members are settled
        if GroupMember.objects.filter(group=group).exclude(net_balance=0).exists():
            return JsonResponse({"error": "Cannot delete group with outstanding balances."}, status=400)
            
        group.delete()
        return JsonResponse({"status": "ok"})


@method_decorator(csrf_exempt, name="dispatch")
class SplitLeaveGroupAPIView(View):
    """POST /api/split/groups/<id>/leave/"""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        user = request.api_user
        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)
            
        if membership.net_balance != 0:
            return JsonResponse({"error": "You cannot leave the group until your balances are settled."}, status=400)
            
        group = membership.group
        membership.delete()
        
        # If group has no members left, delete it
        if group.members.count() == 0:
            group.delete()
            
        return JsonResponse({"message": "You have left the group."})
@method_decorator(csrf_exempt, name="dispatch")
class SplitExpenseCreateAPIView(View):
    """POST /api/split/groups/<id>/expenses/ — add an expense."""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        user = request.api_user
        data = parse_json_body(request)

        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)
            
        if not membership.is_accepted and membership.group.created_by != user:
            return JsonResponse({"error": "You must accept the invitation first."}, status=403)

        group = membership.group
        description = data.get("description", "").strip()
        if not description:
            return JsonResponse({"error": "Description is required."}, status=400)

        try:
            amount = Decimal(str(data.get("amount", "0")))
            if amount <= 0:
                return JsonResponse({"error": "Amount must be positive."}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)

        split_type = data.get("split_type", "equal")
        paid_by_id = data.get("paid_by")
        paid_by_user = user
        if paid_by_id:
            try:
                paid_by_user = User.objects.get(id=paid_by_id)
            except User.DoesNotExist:
                return JsonResponse({"error": "paid_by user not found."}, status=404)

        # Build splits_data for exact/percentage
        splits_data = None
        if split_type in ("exact", "percentage"):
            raw_splits = data.get("splits", [])
            if not raw_splits:
                return JsonResponse({"error": "Per-member split values are required."}, status=400)
            splits_data = []
            for s in raw_splits:
                try:
                    member_user = User.objects.get(id=s["user_id"])
                except User.DoesNotExist:
                    return JsonResponse({"error": f"User {s.get('user_id')} not found."}, status=404)
                try:
                    val_dec = Decimal(str(s.get("value", 0)) or "0")
                except Exception:
                    return JsonResponse({"error": f"Invalid value for user {member_user.id}"}, status=400)
                splits_data.append({"user": member_user, "value": val_dec})

        # De-duplication check
        local_id = data.get("local_id")
        if local_id:
            existing = Expense.objects.filter(group=group, local_id=local_id).first()
            if existing:
                return JsonResponse({
                    "expense": {
                        "id": existing.id,
                        "description": existing.description,
                        "amount": str(existing.amount),
                        "paid_by": existing.paid_by.username,
                    },
                    "already_existed": True
                }, status=200)

        date_str = data.get("date")
        expense_date = None
        if date_str:
            from dateutil.parser import parse as parse_date
            try:
                expense_date = parse_date(date_str)
            except Exception:
                pass

        try:
            expense = create_expense(
                group=group,
                paid_by=paid_by_user,
                created_by=user,
                amount=amount,
                description=description,
                split_type=split_type,
                splits_data=splits_data,
                local_id=local_id,
                date=expense_date
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

        category = str(data.get("category") or "")[:30]
        if category:
            expense.category = category
            expense.save(update_fields=["category"])

        return JsonResponse({
            "expense": {
                "id": expense.id,
                "description": expense.description,
                "amount": str(expense.amount),
                "paid_by": expense.paid_by.username,
            }
        }, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class SplitExpenseDetailAPIView(View):
    """GET /api/split/groups/<group_pk>/expenses/<pk>/ — detail, edit, delete."""

    @method_decorator(api_login_required)
    def get(self, request, group_pk, pk):
        try:
            expense = Expense.objects.select_related("paid_by", "group").get(group_id=group_pk, id=pk)
        except Expense.DoesNotExist:
            return JsonResponse({"error": "Expense not found."}, status=404)
        
        splits = expense.splits.select_related("user").all()
        
        return JsonResponse({
            "expense": {
                "id": expense.id,
                "description": expense.description,
                "category": expense.category,
                "amount": str(expense.amount),
                "date": expense.date.isoformat(),
                "paid_by": get_user_data(request, expense.paid_by),
                "created_by_id": expense.created_by.id if expense.created_by else expense.paid_by.id,
                "split_type": expense.split_type,
                "splits": [
                    {
                        **get_user_data(request, s.user),
                        "user_id": s.user.id,
                        "amount": str(s.amount_owed),
                        "value": str(s.percentage) if expense.split_type == 'percentage' else str(s.amount_owed)
                    }
                    for s in splits
                ]
            }
        })

    @method_decorator(api_login_required)
    def patch(self, request, group_pk, pk):
        user = request.api_user
        data = parse_json_body(request)
        
        try:
            expense = Expense.objects.select_related("group").get(group_id=group_pk, id=pk)
        except Expense.DoesNotExist:
            return JsonResponse({"error": "Expense not found."}, status=404)
        # Permission: Only the creator (or paid_by for legacy) can edit
        owner_id = expense.created_by_id if expense.created_by else expense.paid_by_id
        if user.id != owner_id:
             return JsonResponse({"error": "Permission denied. You can only edit your own entries."}, status=403)

        description = data.get("description", expense.description).strip()
        try:
            amount = Decimal(str(data.get("amount", expense.amount)))
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)
            
        split_type = data.get("split_type", expense.split_type)
        
        splits_data = None
        if split_type in ("exact", "percentage"):
            raw_splits = data.get("splits", [])
            if raw_splits:
                splits_data = []
                for s in raw_splits:
                    try:
                        member_user = User.objects.get(id=s["user_id"])
                        try:
                            val_dec = Decimal(str(s.get("value", 0)) or "0")
                        except Exception:
                            return JsonResponse({"error": f"Invalid value for user {member_user.id}"}, status=400)
                        splits_data.append({"user": member_user, "value": val_dec})
                    except User.DoesNotExist:
                        return JsonResponse({"error": f"User {s.get('user_id')} not found."}, status=404)
        
        paid_by_user = expense.paid_by
        paid_by_id = data.get("paid_by")
        if paid_by_id:
            try:
                paid_by_user = User.objects.get(id=paid_by_id)
            except User.DoesNotExist:
                return JsonResponse({"error": "paid_by user not found."}, status=404)

        date_str = data.get("date")
        expense_date = expense.date
        if date_str:
            from dateutil.parser import parse as parse_date
            try:
                expense_date = parse_date(date_str)
            except Exception:
                pass

        from split_expense.services import update_expense
        try:
            old_category = expense.category
            new_exp = update_expense(expense, paid_by_user, amount, description, split_type, splits_data, date=expense_date)
            new_exp.category = str(data.get("category", old_category) or "")[:30]
            new_exp.save(update_fields=["category"])
            return JsonResponse({
                "expense": {
                    "id": new_exp.id,
                    "description": new_exp.description,
                    "amount": str(new_exp.amount),
                }
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

    @method_decorator(api_login_required)
    def delete(self, request, group_pk, pk):
        user = request.api_user
        try:
            expense = Expense.objects.select_related("group").get(group_id=group_pk, id=pk)
        except Expense.DoesNotExist:
            return JsonResponse({"error": "Expense not found."}, status=404)
        if user.id != (expense.created_by_id if expense.created_by else expense.paid_by_id):
             return JsonResponse({"error": "Permission denied. You can only delete your own entries."}, status=403)

        from split_expense.services import delete_expense
        try:
            delete_expense(expense, deleted_by=user)
            return JsonResponse({"message": "Expense deleted."})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class SplitSettleAPIView(View):
    """POST /api/split/groups/<id>/settle/ — settle a debt."""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        user = request.api_user
        data = parse_json_body(request)

        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)

        group = membership.group

        try:
            amount = Decimal(str(data.get("amount", "0")))
            if amount <= 0:
                return JsonResponse({"error": "Amount must be positive."}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Invalid amount."}, status=400)

        paid_to_id = data.get("paid_to_id")
        paid_by_id = data.get("paid_by_id")
        
        if not paid_to_id:
            return JsonResponse({"error": "paid_to_id is required."}, status=400)

        try:
            paid_to_user = User.objects.get(id=paid_to_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "Receiver user not found."}, status=404)
            
        if paid_by_id:
            try:
                paid_by_user = User.objects.get(id=paid_by_id)
            except User.DoesNotExist:
                return JsonResponse({"error": "Payer user not found."}, status=404)
        else:
            paid_by_user = user
            
        if user != paid_by_user and user != paid_to_user and user != group.created_by:
            return JsonResponse({"error": "You don't have permission to record this settlement."}, status=403)

        # De-duplication check
        local_id = data.get("local_id")
        if local_id:
            existing = Settlement.objects.filter(group=group, local_id=local_id).first()
            if existing:
                return JsonResponse({
                    "settlement": {"id": existing.id, "amount": str(existing.amount)},
                    "already_existed": True
                }, status=200)

        try:
            settlement = create_settlement(
                group=group,
                paid_by=paid_by_user,
                paid_to=paid_to_user,
                amount=amount,
                local_id=local_id
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({
            "settlement": {
                "id": settlement.id,
                "amount": str(settlement.amount),
            }
        }, status=201)


@method_decorator(csrf_exempt, name="dispatch")
class SplitAddMemberAPIView(View):
    """POST /api/split/groups/<id>/members/ — add a member by username."""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        user = request.api_user
        data = parse_json_body(request)

        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)

        group = membership.group
        if not group.members_can_invite and user.id != group.created_by_id:
            return JsonResponse({"error": "Only the group admin can invite people to this group."}, status=403)
        user_ids = data.get("user_ids", [])
        identifier = data.get("identifier", "").strip()

        from split_expense.services import invite_user_to_group

        if not user_ids and identifier:
            success, msg = invite_user_to_group(group, identifier, user, request=request)
            if success:
                return JsonResponse({"status": "ok", "message": msg})
            else:
                return JsonResponse({"error": msg}, status=400)

        if not user_ids:
            return JsonResponse({"error": "No users selected."}, status=400)

        count = 0
        for uid in user_ids:
            success, msg = invite_user_to_group(group, str(uid), user, request=request)
            if success: count += 1

        return JsonResponse({"status": "ok", "count": count})


@method_decorator(csrf_exempt, name="dispatch")
class SplitInviteManageAPIView(View):
    """POST /api/split/groups/<pk>/invites/<action>/ — action "resend" or "cancel".

    Body: {"email": "..."} for someone invited by email, or {"user_id": n} for an app
    user who has not accepted yet. Anyone who may invite to the group may do this.
    """

    @method_decorator(api_login_required)
    def post(self, request, pk, action):
        from split_expense.models import GroupInvitation
        from split_expense.services import (
            _send_external_group_invitation_email,
            _send_group_invitation_notification,
        )

        user = request.api_user
        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user, is_accepted=True)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)
        group = membership.group
        if not group.members_can_invite and user.id != group.created_by_id:
            return JsonResponse({"error": "Only the group admin can manage invites."}, status=403)
        if action not in ("resend", "cancel"):
            return JsonResponse({"error": "Unknown action."}, status=400)

        data = parse_json_body(request)
        email = (data.get("email") or "").strip().lower()
        user_id = data.get("user_id")

        if email:
            invite = GroupInvitation.objects.filter(group=group, email__iexact=email).first()
            if not invite:
                return JsonResponse({"error": "Invite not found."}, status=404)
            if action == "cancel":
                invite.delete()
                return JsonResponse({"status": "ok", "message": f"Invite to {email} cancelled."})
            _send_external_group_invitation_email(group, invite, user, request=request)
            return JsonResponse({"status": "ok", "message": f"Invite sent again to {email}."})

        if user_id is not None:
            pending = GroupMember.objects.filter(group=group, user_id=user_id, is_accepted=False).select_related("user").first()
            if not pending:
                return JsonResponse({"error": "No pending invite for this person."}, status=404)
            if action == "cancel":
                pending.delete()
                return JsonResponse({"status": "ok", "message": "Invite cancelled."})
            _send_group_invitation_notification(group, pending.user, request=request, inviter=user)
            return JsonResponse({"status": "ok", "message": "Invite sent again."})

        return JsonResponse({"error": "Give an email or a user_id."}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class SplitRemoveMemberAPIView(View):
    """POST /api/split/groups/<group_id>/members/<user_id>/remove/"""

    @method_decorator(api_login_required)
    def post(self, request, group_id, user_id):
        user = request.api_user
        try:
            membership = GroupMember.objects.select_related("group").get(group_id=group_id, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)

        group = membership.group
        
        if user != group.created_by and user.id != user_id:
            return JsonResponse({"error": "Only the group creator can remove other members."}, status=403)
            
        if user_id == group.created_by.id:
            return JsonResponse({"error": "The group creator cannot be removed."}, status=400)

        from django.contrib.auth.models import User
        try:
            user_to_remove = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found."}, status=404)

        from split_expense.services import remove_member
        from django.core.exceptions import ValidationError

        try:
            remove_member(group, user_to_remove)
            return JsonResponse({"status": "ok", "message": "Member removed."})
        except ValidationError as e:
            return JsonResponse({"error": str(e.message)}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class SplitUserSearchAPIView(View):
    """GET /api/split/users/search/?q=... — search users by username/email."""

    @method_decorator(api_login_required)
    def get(self, request):
        from django.db.models import Q
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"users": []})

        users = User.objects.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
        ).exclude(id=request.api_user.id).exclude(is_active=False)[:5]

        return JsonResponse({"users": [
            {"id": u.id, "username": u.username, "email": u.email, "initial": u.username[0].upper()}
            for u in users
        ]})


@method_decorator(csrf_exempt, name="dispatch")
class SplitReminderAPIView(View):
    """POST /api/split/groups/<id>/remind/ — send email reminder."""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        user = request.api_user
        data = parse_json_body(request)

        try:
            membership = GroupMember.objects.select_related("group").get(group_id=pk, user=user)
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=404)

        group = membership.group
        user_id = data.get("user_id")
        amount = data.get("amount", "some amount")

        try:
            user_to_remind = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found."}, status=404)

        # Rate limit: 3 per 24 hours
        from django.utils import timezone
        now = timezone.now()

        target_membership = GroupMember.objects.filter(group=group, user=user_to_remind).first()
        if target_membership:
            if target_membership.last_reminded_at and now >= target_membership.last_reminded_at + timezone.timedelta(hours=24):
                target_membership.reminders_sent_today = 0
            
            if target_membership.reminders_sent_today >= 3:
                return JsonResponse({"error": "You can only send 3 reminders per day."}, status=429)

        subject = f"Action needed in '{group.name}'"
        email_body_text = f"Hi {user_to_remind.username},\n\nJust a quick reminder regarding your balance of {amount} in '{group.name}'.\n\nPlease settle up when you can!"
        push_body_text = f"Just a reminder regarding your balance of {amount}. Please settle up!"
        
        # Saved to their Notifications list and pushed; email only if no push went out.
        from accounts.notify import notify
        pushed = notify(
            user_to_remind,
            subject,
            push_body_text,
            data={
                "action": "open_split_group",
                "group_id": str(group.id),
                "group_name": group.name,
                "kind": "split_reminder",
            },
        )

        print(f"[DEBUG FCM API] Push notification successful: {pushed}")
        if not pushed:
            from django.core.mail import send_mail
            from django.template.loader import render_to_string
            from django.conf import settings as conf

            html_message = render_to_string('split_expense/email/payment_reminder.html', {
                'user': user_to_remind,
                'sender_name': user.get_full_name() or user.username,
                'group_name': group.name,
                'amount_owed': amount,
            })

            try:
                send_mail(
                    subject=subject,
                    message=email_body_text,
                    from_email=conf.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_to_remind.email],
                    html_message=html_message,
                    fail_silently=False,
                )
            except Exception as e:
                return JsonResponse({"error": f"Failed to send email: {e}"}, status=500)

        if target_membership:
            if target_membership.reminders_sent_today == 0 or target_membership.last_reminded_at is None:
                target_membership.last_reminded_at = now
            target_membership.reminders_sent_today += 1
            target_membership.save()

        msg = "Push notification sent" if pushed else "Reminder email sent"
        return JsonResponse({"message": f"{msg} to {user_to_remind.username}."})

@method_decorator(csrf_exempt, name="dispatch")
def get_user_data(request, user):
    """Helper to serialize user with full name and avatar."""
    name = f"{user.first_name} {user.last_name}".strip()
    display_name = name if name else user.username
    
    avatar_url = None
    try:
        if user.userprofile.avatar:
            avatar_url = request.build_absolute_uri(user.userprofile.avatar.url)
    except:
        pass
        
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": display_name,
        "avatar_url": avatar_url,
        "initial": (name[0] if name else user.username[0]).upper()
    }

@method_decorator(csrf_exempt, name="dispatch")
class SplitFriendListAPIView(View):
    """GET /api/split/friends/ — list friends & requests. POST — invite friend."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        
        friends = Friendship.objects.filter(user=user).select_related('friend')
        pending_received = FriendRequest.objects.filter(receiver=user, is_accepted=False).select_related('sender')
        pending_sent = FriendRequest.objects.filter(sender=user, is_accepted=False).select_related('receiver')
        
        from split_expense.models import ExternalFriendInvitation
        external_invites = ExternalFriendInvitation.objects.filter(sender=user)
        
        return JsonResponse({
            "friends": [get_user_data(request, f.friend) for f in friends],
            "pending_received": [
                {
                    "id": r.id, 
                    "sender": get_user_data(request, r.sender)
                }
                for r in pending_received
            ],
            "pending_sent": [
                {
                    "id": r.id, 
                    "receiver": get_user_data(request, r.receiver)
                }
                for r in pending_sent
            ] + [
                {
                    "id": f"ext_{inv.id}",
                    "receiver": {
                        "id": -1,
                        "username": inv.email,
                        "display_name": inv.email,
                        "email": inv.email,
                        "initial": "?",
                        "is_external": True
                    }
                }
                for inv in external_invites
            ]
        })

    @method_decorator(api_login_required)
    def post(self, request):
        user = request.api_user
        data = parse_json_body(request)
        email = data.get("email", "").strip()
        
        if not email:
            return JsonResponse({"error": "Email is required."}, status=400)
            
        from split_expense.services import send_friend_request
        try:
            req = send_friend_request(user, email, request=request)
            if isinstance(req, FriendRequest):
                return JsonResponse({
                    "message": f"Friend request sent to {req.receiver.username}.",
                    "user": get_user_data(request, req.receiver)
                }, status=201)
            else:
                return JsonResponse({
                    "message": f"Invitation sent to {email}. They will be added as a friend once they join Espere."
                }, status=201)
        except ValidationError as e:
            return JsonResponse({"error": str(e.message)}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

@method_decorator(csrf_exempt, name="dispatch")
class SplitFriendActionAPIView(View):
    """POST /api/split/friends/action/ {request_id, action: 'accept'|'reject'|'cancel'}"""

    @method_decorator(api_login_required)
    def post(self, request):
        user = request.api_user
        data = parse_json_body(request)
        rid = data.get("request_id")
        action = data.get("action")
        
        try:
            if action in ('accept', 'reject'):
                req = FriendRequest.objects.get(id=rid, receiver=user)
                if action == 'accept':
                    Friendship.objects.get_or_create(user=user, friend=req.sender)
                    Friendship.objects.get_or_create(user=req.sender, friend=user)
                    req.is_accepted = True
                    req.save()
                    return JsonResponse({"message": "Friend request accepted."})
                else:
                    req.delete()
                    return JsonResponse({"message": "Friend request rejected."})
            elif action == 'remove':
                friend_id = data.get("friend_id")
                try:
                    from django.contrib.auth.models import User
                    friend = User.objects.get(id=friend_id)
                    Friendship.objects.filter(user=user, friend=friend).delete()
                    Friendship.objects.filter(user=friend, friend=user).delete()
                    return JsonResponse({"message": "Friend removed."})
                except User.DoesNotExist:
                    return JsonResponse({"error": "User not found."}, status=404)
            elif action == 'cancel':
                if str(rid).startswith('ext_'):
                    from split_expense.models import ExternalFriendInvitation
                    ext_id = int(str(rid).replace('ext_', ''))
                    inv = ExternalFriendInvitation.objects.get(id=ext_id, sender=user)
                    inv.delete()
                    return JsonResponse({"message": "Invitation revoked."})
                req = FriendRequest.objects.get(id=rid, sender=user)
                req.delete()
                return JsonResponse({"message": "Friend request cancelled."})
            else:
                return JsonResponse({"error": "Invalid action."}, status=400)
        except FriendRequest.DoesNotExist:
            return JsonResponse({"error": "Request not found."}, status=404)

@method_decorator(csrf_exempt, name="dispatch")
class SplitInvitationListAPIView(View):
    """GET /api/split/invitations/ — list pending group invitations."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        invites = GroupMember.objects.filter(user=user, is_accepted=False).select_related('group', 'group__created_by')
        
        return JsonResponse({
            "invitations": [
                {
                    "id": inv.id,
                    "group_id": inv.group.id,
                    "group_name": inv.group.name,
                    "invited_by": inv.group.created_by.username
                }
                for inv in invites
            ]
        })

@method_decorator(csrf_exempt, name="dispatch")
class SplitInvitationActionAPIView(View):
    """POST /api/split/invitations/<pk>/action/ {action: 'accept'|'reject'}"""

    @method_decorator(api_login_required)
    def post(self, request, pk):
        user = request.api_user
        data = parse_json_body(request)
        action = data.get("action")
        
        try:
            membership = GroupMember.objects.get(id=pk, user=user)
            if action == 'accept':
                membership.is_accepted = True
                membership.save()
                
                if membership.invited_by:
                    from split_expense.models import Friendship
                    Friendship.objects.get_or_create(user=user, friend=membership.invited_by)
                    Friendship.objects.get_or_create(user=membership.invited_by, friend=user)
                    
                return JsonResponse({"message": "Invitation accepted."})
            else:
                membership.delete()
                return JsonResponse({"message": "Invitation rejected."})
        except GroupMember.DoesNotExist:
            return JsonResponse({"error": "Invitation not found."}, status=404)

@method_decorator(csrf_exempt, name="dispatch")
class SplitTokenInviteAPIView(View):
    """GET/POST /api/split/invite/<uuid:token>/"""
    
    def get(self, request, token):
        from split_expense.models import GroupInvitation, Group
        try:
            invite = GroupInvitation.objects.get(token=token)
            return JsonResponse({
                "valid": True,
                "group_name": invite.group.name,
                "invited_by": invite.invited_by.username if invite.invited_by else "Someone",
                "email": invite.email
            })
        except GroupInvitation.DoesNotExist:
            try:
                group = Group.objects.get(invite_token=token)
                
                # Retrieve ref if present in the UI layer, here we just return it's valid
                return JsonResponse({
                    "valid": True,
                    "group_name": group.name,
                    "invited_by": "A group member",
                    "email": None
                })
            except Group.DoesNotExist:
                return JsonResponse({"error": "Invalid or expired invitation token.", "valid": False}, status=404)

    @method_decorator(api_login_required)
    def post(self, request, token):
        from split_expense.models import GroupInvitation, GroupMember, Group, Friendship
        user = request.api_user
        
        # First check if it's an email invite
        try:
            invite = GroupInvitation.objects.get(token=token)
            
            if user.email.lower() != invite.email.lower():
                return JsonResponse({"error": f"This invite is for {invite.email}. You are logged in as {user.email}."}, status=403)
                
            membership, created = GroupMember.objects.get_or_create(
                group=invite.group,
                user=user,
                defaults={'is_accepted': True, 'invited_by': invite.invited_by}
            )
            
            if not created and not membership.is_accepted:
                membership.is_accepted = True
                membership.invited_by = invite.invited_by
                membership.save()
                
            if invite.invited_by:
                Friendship.objects.get_or_create(user=user, friend=invite.invited_by)
                Friendship.objects.get_or_create(user=invite.invited_by, friend=user)
            
            invite.delete()
            return JsonResponse({"message": "Successfully joined the group!", "group_id": invite.group.id})
            
        except GroupInvitation.DoesNotExist:
            pass

        # Then check if it's a generic group invite
        try:
            group = Group.objects.get(invite_token=token)
            
            data = parse_json_body(request)
            ref_username = data.get("ref", "")
            
            invited_by_user = None
            if ref_username:
                try:
                    invited_by_user = User.objects.get(username=ref_username)
                except User.DoesNotExist:
                    pass
            
            # Enforce members_can_invite
            if not group.members_can_invite:
                if invited_by_user and invited_by_user != group.created_by:
                    return JsonResponse({"error": "Only the group owner can invite new members."}, status=403)
                # If no ref is passed but the group restricts it, they technically shouldn't be able to join via arbitrary link
                # but we can allow it if they somehow got the token directly, or we can reject it
                if not invited_by_user:
                    return JsonResponse({"error": "Only the group owner can invite new members."}, status=403)

            membership, created = GroupMember.objects.get_or_create(
                group=group,
                user=user,
                defaults={'is_accepted': True, 'invited_by': invited_by_user}
            )
            
            if not created and not membership.is_accepted:
                membership.is_accepted = True
                membership.invited_by = invited_by_user
                membership.save()
                
            if invited_by_user:
                Friendship.objects.get_or_create(user=user, friend=invited_by_user)
                Friendship.objects.get_or_create(user=invited_by_user, friend=user)
            
            return JsonResponse({"message": "Successfully joined the group!", "group_id": group.id})
            
        except Group.DoesNotExist:
            return JsonResponse({"error": "Invalid or expired invitation token."}, status=404)


@method_decorator(csrf_exempt, name="dispatch")
class ForgotPasswordAPIView(View):
    """POST /api/auth/forgot-password/ — sends OTP for password reset."""

    def post(self, request):
        data = parse_json_body(request)
        email = data.get("email", "").strip()

        if not email:
            return JsonResponse({"error": "Email is required."}, status=400)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return JsonResponse({"message": "If the email is registered, a password reset OTP has been sent."}, status=200)

        from accounts.models import PasswordResetToken
        from django.core.mail import send_mail
        from django.template.loader import render_to_string
        from django.conf import settings

        # Delete old tokens
        PasswordResetToken.objects.filter(user=user).delete()

        # Create and send new token
        token_obj = PasswordResetToken.objects.create(user=user)
        
        try:
            subject = "Password Reset Request - Espere"
            html_message = render_to_string("accounts/password_reset_email.html", {
                "user": user,
                "otp": token_obj.token,
            })
            send_mail(
                subject=subject,
                message=f"Your password reset OTP is {token_obj.token}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
        except Exception as e:
            print(f"Error sending password reset email: {e}")

        return JsonResponse({"message": "If the email is registered, a password reset OTP has been sent."}, status=200)


@method_decorator(csrf_exempt, name="dispatch")
class VerifyPasswordResetOTPAPIView(View):
    """POST /api/auth/verify-password-reset-otp/ — verifies the OTP for password reset."""

    def post(self, request):
        data = parse_json_body(request)
        email = data.get("email", "").strip()
        otp = data.get("otp", "").strip()

        if not email or not otp:
            return JsonResponse({"error": "Email and OTP are required."}, status=400)

        from accounts.models import PasswordResetToken
        try:
            token_obj = PasswordResetToken.objects.get(user__email__iexact=email, token=otp)
            return JsonResponse({"message": "OTP verified successfully. You can now reset your password."}, status=200)
        except PasswordResetToken.DoesNotExist:
            return JsonResponse({"error": "Invalid or expired OTP."}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class ResetPasswordAPIView(View):
    """POST /api/auth/reset-password/ — sets a new password using a verified OTP."""

    def post(self, request):
        data = parse_json_body(request)
        email = data.get("email", "").strip()
        otp = data.get("otp", "").strip()
        new_password = data.get("new_password", "")

        if not email or not otp or not new_password:
            return JsonResponse({"error": "Email, OTP, and new password are required."}, status=400)

        if len(new_password) < 6:
            return JsonResponse({"error": "Password must be at least 6 characters long."}, status=400)

        from accounts.models import PasswordResetToken
        try:
            token_obj = PasswordResetToken.objects.get(user__email__iexact=email, token=otp)
            user = token_obj.user
            user.set_password(new_password)
            user.save()
            token_obj.delete()
            return JsonResponse({"message": "Password reset successfully. You can now log in."}, status=200)
        except PasswordResetToken.DoesNotExist:
            return JsonResponse({"error": "Invalid or expired OTP."}, status=400)
