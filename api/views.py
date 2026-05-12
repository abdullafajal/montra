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
        DeviceToken.objects.get_or_create(user=request.api_user, token=token)
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

        if errors:
            return JsonResponse({"errors": errors}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=True,  # For mobile, skip email verification
        )
        UserProfile.objects.get_or_create(user=user)
        token = APIToken.generate_token(user)
        return JsonResponse({
            "token": token.key,
            "user": _user_profile_data(user),
        }, status=201)


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


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class DashboardAPIView(View):
    """GET /api/dashboard/ — aggregated dashboard data."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        now = timezone.now()
        today = now.date()
        month_start = today.replace(day=1)

        # Monthly stats
        month_txns = Transaction.objects.filter(
            user=user, date__date__gte=month_start, date__date__lte=today
        )
        income = month_txns.filter(type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        expenses = month_txns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")

        # All-time balance
        all_income = Transaction.objects.filter(user=user, type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        all_expenses = Transaction.objects.filter(user=user, type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        total_balance = all_income - all_expenses

        # Recent transactions
        recent = Transaction.objects.filter(user=user).select_related("category")[:5]
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

        # Chart data: monthly income vs expense (last 6 months)
        bar_labels, bar_income, bar_expense = [], [], []
        for i in range(5, -1, -1):
            m = (today.month - i - 1) % 12 + 1
            y = today.year - ((today.month - i - 1) < 0)
            if today.month - i <= 0:
                y = today.year - 1
                m = 12 + (today.month - i)
            month_label = date(y, m, 1).strftime("%b")
            bar_labels.append(month_label)
            mtxns = Transaction.objects.filter(user=user, date__year=y, date__month=m)
            bar_income.append(float(mtxns.filter(type="income").aggregate(t=Sum("amount"))["t"] or 0))
            bar_expense.append(float(mtxns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or 0))

        # Chart data: 30-day spending trend
        line_labels, line_values = [], []
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            daily = Transaction.objects.filter(
                user=user, type="expense", date__date=d
            ).aggregate(t=Sum("amount"))["t"] or 0
            line_labels.append(d.strftime("%d"))
            line_values.append(float(daily))

        # Budget warnings
        budgets = Budget.objects.filter(user=user).select_related("category")
        budget_warnings = [
            {
                "category": b.category.name,
                "icon": b.category.icon,
                "color": b.category.color
            }
            for b in budgets if b.is_exceeded()
        ]

        # Insights
        insights = _generate_insights(user, today, income, expenses)

        return JsonResponse({
            "greeting": _get_greeting(),
            "user": _user_profile_data(user),
            "total_balance": str(total_balance),
            "monthly_income": str(income),
            "monthly_expenses": str(expenses),
            "monthly_savings": str(income - expenses),
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


@method_decorator(csrf_exempt, name="dispatch")
class ReportAPIView(View):
    """GET /api/reports/ — yearly report data."""

    @method_decorator(api_login_required)
    def get(self, request):
        from reports.views import ReportsView
        user = request.api_user
        today = timezone.now().date()
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
            insights.append(f"📈 You spent {abs(change):.0f}% more than last month.")
        elif change < -5:
            insights.append(f"📉 Great! You spent {abs(change):.0f}% less than last month.")

    if current_income > current_expenses:
        savings_rate = ((current_income - current_expenses) / current_income) * 100
        insights.append(f"💰 Your savings rate this month is {savings_rate:.0f}%.")

    if current_expenses > current_income and current_income > 0:
        insights.append("⚠️ You're spending more than you earn this month!")

    if not insights:
        insights.append("💡 Start tracking your expenses to get personalized insights!")

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

        # Pagination
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 50))
        total = qs.count()
        offset = (page - 1) * per_page
        transactions = qs[offset:offset + per_page]

        profile, _ = UserProfile.objects.get_or_create(user=user)
        cs = profile.get_currency_symbol()

        return JsonResponse({
            "transactions": [_transaction_to_dict(t, cs) for t in transactions],
            "total": total,
            "page": page,
            "per_page": per_page,
            "has_next": offset + per_page < total,
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
        return JsonResponse({
            "categories": [_category_to_dict(c) for c in categories]
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

        category = Category.objects.create(
            name=name,
            icon=icon,
            color=color,
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

@method_decorator(csrf_exempt, name="dispatch")
class BudgetListAPIView(View):
    """GET /api/budgets/ — list budgets with spent info."""

    @method_decorator(api_login_required)
    def get(self, request):
        user = request.api_user
        budgets = Budget.objects.filter(user=user).select_related("category")
        data = []
        for b in budgets:
            data.append({
                "id": b.id,
                "category": _category_to_dict(b.category),
                "amount": str(b.amount),
                "month": b.month.isoformat(),
                "spent": str(b.get_spent()),
                "percentage": b.get_percentage(),
                "is_exceeded": b.is_exceeded(),
            })
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return JsonResponse({
            "budgets": data,
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
                from datetime import datetime
                month_date = datetime.strptime(month_str, "%Y-%m-%d").date().replace(day=1)
            except (ValueError, TypeError):
                pass

        budget, created = Budget.objects.update_or_create(
            user=user, category=category,
            defaults={"amount": amount, "month": month_date},
        )
        return JsonResponse({
            "budget": {
                "id": budget.id,
                "category": _category_to_dict(budget.category),
                "amount": str(budget.amount),
                "month": budget.month.isoformat(),
                "spent": str(budget.get_spent()),
                "percentage": budget.get_percentage(),
                "is_exceeded": budget.is_exceeded(),
            }
        }, status=201 if created else 200)


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
from split_expense.models import Group, GroupMember, Expense, ExpenseSplit, Settlement
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
            })
        return JsonResponse({"groups": data})

    @method_decorator(api_login_required)
    def post(self, request):
        data = parse_json_body(request)
        user = request.api_user

        name = data.get("name", "").strip()
        if not name:
            return JsonResponse({"error": "Group name is required."}, status=400)

        group = Group.objects.create(name=name, created_by=user)
        GroupMember.objects.create(group=group, user=user, is_accepted=True)

        # Add other members by username
        member_usernames = data.get("members", [])
        for uname in member_usernames:
            uname = uname.strip()
            if uname and uname != user.username:
                try:
                    member_user = User.objects.get(username=uname)
                    GroupMember.objects.get_or_create(
                        group=group, user=member_user,
                        defaults={"is_accepted": True}
                    )
                except User.DoesNotExist:
                    pass  # Skip unknown users

        return JsonResponse({
            "group": {
                "id": group.id,
                "name": group.name,
                "total_members": group.members.count(),
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
            
        group = membership.group
        
        # members
        members_data = []
        for gm in GroupMember.objects.filter(group=group).select_related("user"):
            members_data.append({
                "id": gm.user.id,
                "username": gm.user.username,
                "net_balance": str(gm.net_balance),
            })
            
        # expenses
        expenses_data = []
        for ex in Expense.objects.filter(group=group).select_related("paid_by").order_by("-date", "-created_at")[:50]:
            expenses_data.append({
                "id": ex.id,
                "description": ex.description,
                "amount": str(ex.amount),
                "paid_by": ex.paid_by.username,
                "paid_by_id": ex.paid_by.id,
                "split_type": ex.split_type,
                "date": ex.date.isoformat(),
            })

        # simplified debts
        debts = calculate_simplified_debts(group)
        debts_data = []
        for d in debts:
            debts_data.append({
                "from_user": d["from"].username,
                "from_user_id": d["from"].id,
                "to_user": d["to"].username,
                "to_user_id": d["to"].id,
                "amount": str(d["amount"]),
            })

        # settlements
        settlements_data = []
        for s in Settlement.objects.filter(group=group).select_related("paid_by", "paid_to").order_by("-date")[:20]:
            settlements_data.append({
                "id": s.id,
                "paid_by": s.paid_by.username,
                "paid_to": s.paid_to.username,
                "amount": str(s.amount),
                "date": s.date.isoformat(),
            })

        return JsonResponse({
            "group": {
                "id": group.id,
                "name": group.name,
                "my_net_balance": str(membership.net_balance),
                "members": members_data,
                "recent_expenses": expenses_data,
                "simplified_debts": debts_data,
                "settlements": settlements_data,
            }
        })


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
        paid_by_id = data.get("paid_by_id")

        if paid_by_id:
            try:
                paid_by_user = User.objects.get(id=paid_by_id)
            except User.DoesNotExist:
                paid_by_user = user
        else:
            paid_by_user = user

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
                splits_data.append({"user": member_user, "value": Decimal(str(s["value"]))})

        try:
            expense = create_expense(
                group=group,
                paid_by=paid_by_user,
                amount=amount,
                description=description,
                split_type=split_type,
                splits_data=splits_data,
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({
            "expense": {
                "id": expense.id,
                "description": expense.description,
                "amount": str(expense.amount),
                "paid_by": expense.paid_by.username,
            }
        }, status=201)


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
        if not paid_to_id:
            return JsonResponse({"error": "paid_to_id is required."}, status=400)

        try:
            paid_to_user = User.objects.get(id=paid_to_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found."}, status=404)

        try:
            settlement = create_settlement(
                group=group,
                paid_by=user,
                paid_to=paid_to_user,
                amount=amount,
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
        identifier = data.get("identifier", "").strip()
        if not identifier:
            return JsonResponse({"error": "Username or email is required."}, status=400)

        # Try username then email
        user_to_add = User.objects.filter(username=identifier).first()
        if not user_to_add:
            user_to_add = User.objects.filter(email__iexact=identifier).first()

        if not user_to_add:
            return JsonResponse({"error": f"User '{identifier}' not found."}, status=404)

        if group.members.filter(id=user_to_add.id).exists():
            return JsonResponse({"error": f"{user_to_add.username} is already a member."}, status=400)

        GroupMember.objects.create(group=group, user=user_to_add, is_accepted=False)
        return JsonResponse({
            "message": f"Invitation sent to {user_to_add.username}.",
            "member": {
                "id": user_to_add.id,
                "username": user_to_add.username,
            }
        }, status=201)


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
        
        # Try pushing notification first
        pushed = False
        from accounts.models import DeviceToken
        from config.firebase import send_push_notification
        
        tokens = DeviceToken.objects.filter(user=user_to_remind)
        if tokens.exists():
            for dt in tokens:
                success = send_push_notification(
                    token=dt.token, 
                    title=subject, 
                    body=push_body_text,
                    data={
                        "action": "open_split_group",
                        "group_id": str(group.id),
                        "group_name": group.name,
                    }
                )
                if success:
                    pushed = True

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
