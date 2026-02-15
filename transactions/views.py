"""Transactions views — Dashboard, CRUD, Categories, Budgets, Savings."""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Q, Count
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DeleteView, View,
)
from django.contrib import messages

from .models import Transaction, Category, Budget, SavingsGoal
from .forms import TransactionForm, CategoryForm, BudgetForm, SavingsGoalForm


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "transactions/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()
        today = now.date()

        # --- Current month stats ---
        month_start = today.replace(day=1)
        month_txns = Transaction.objects.filter(user=user, date__date__gte=month_start, date__date__lte=today)

        income = month_txns.filter(type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        expenses = month_txns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        balance = income - expenses

        # All-time balance
        all_income = Transaction.objects.filter(user=user, type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        all_expenses = Transaction.objects.filter(user=user, type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")
        total_balance = all_income - all_expenses

        # Recent transactions
        recent = Transaction.objects.filter(user=user)[:5]

        # --- Chart data: Expenses by category (pie) ---
        cat_data = (
            month_txns.filter(type="expense")
            .values("category__name", "category__color")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:8]
        )
        pie_labels = [d["category__name"] or "Other" for d in cat_data]
        pie_values = [float(d["total"]) for d in cat_data]
        pie_colors = [d["category__color"] or "#6366f1" for d in cat_data]

        # --- Chart data: Monthly income vs expense (bar — last 6 months) ---
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

        # --- Chart data: Spending trend (line — last 30 days) ---
        line_labels, line_values = [], []
        for i in range(29, -1, -1):
            d = today - timedelta(days=i)
            daily = Transaction.objects.filter(
                user=user, type="expense", date__date=d
            ).aggregate(t=Sum("amount"))["t"] or 0
            line_labels.append(d.strftime("%d"))
            line_values.append(float(daily))

        # --- Financial insights ---
        insights = self._generate_insights(user, today, income, expenses)

        # --- Budget warnings ---
        budgets = Budget.objects.filter(user=user, month=month_start)
        budget_warnings = [b for b in budgets if b.is_exceeded()]

        ctx.update({
            "greeting": self._get_greeting(),
            "total_balance": total_balance,
            "monthly_income": income,
            "monthly_expenses": expenses,
            "monthly_savings": income - expenses,
            "recent_transactions": recent,
            "pie_labels": json.dumps(pie_labels),
            "pie_values": json.dumps(pie_values),
            "pie_colors": json.dumps(pie_colors),
            "bar_labels": json.dumps(bar_labels),
            "bar_income": json.dumps(bar_income),
            "bar_expense": json.dumps(bar_expense),
            "line_labels": json.dumps(line_labels),
            "line_values": json.dumps(line_values),
            "budget_warnings": budget_warnings,
            "insights": insights,
        })
        return ctx


    @staticmethod
    def _get_greeting():
        hour = timezone.localtime().hour
        if 5 <= hour < 12:
            return "Morning"
        elif 12 <= hour < 17:
            return "Afternoon"
        elif 17 <= hour < 21:
            return "Evening"
        return "Night"

    def _generate_insights(self, user, today, current_income, current_expenses):
        """Generate smart financial insight messages."""
        insights = []
        # Compare with last month
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
# Transaction CRUD
# ---------------------------------------------------------------------------
class TransactionListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "transactions/transaction_list.html"
    context_object_name = "transactions"
    paginate_by = 50

    def _get_active_month(self):
        """Return (year, month) tuple or None if 'all' mode."""
        if self.request.GET.get("all") == "1":
            return None
        month_param = self.request.GET.get("month", "")
        if month_param:
            try:
                y, m = map(int, month_param.split("-"))
                return (y, m)
            except ValueError:
                pass
        # Default: current month
        today = timezone.localdate()
        return (today.year, today.month)

    def get_queryset(self):
        qs = Transaction.objects.filter(user=self.request.user).order_by(
            "-date", "-created_at"
        )
        # Search
        q = self.request.GET.get("q", "")
        if q:
            qs = qs.filter(Q(notes__icontains=q) | Q(category__name__icontains=q))
        # Type
        txn_type = self.request.GET.get("type", "")
        if txn_type in ("income", "expense"):
            qs = qs.filter(type=txn_type)
        # Category
        cat_id = self.request.GET.get("category", "")
        if cat_id:
            qs = qs.filter(category_id=cat_id)
        # Month
        active = self._get_active_month()
        if active:
            qs = qs.filter(date__year=active[0], date__month=active[1])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = Category.objects.filter(
            Q(is_system=True) | Q(user=self.request.user)
        )

        active = self._get_active_month()
        show_all = active is None

        if active:
            import datetime as _dt

            cur = _dt.date(active[0], active[1], 1)
            # Previous month
            prev = (cur - _dt.timedelta(days=1)).replace(day=1)
            # Next month
            if cur.month == 12:
                nxt = cur.replace(year=cur.year + 1, month=1)
            else:
                nxt = cur.replace(month=cur.month + 1)
            ctx["month_label"] = cur.strftime("%B %Y")
            ctx["month_current"] = cur.strftime("%Y-%m")
            ctx["month_prev"] = prev.strftime("%Y-%m")
            ctx["month_next"] = nxt.strftime("%Y-%m")
        else:
            ctx["month_label"] = "All Time"
            ctx["month_current"] = ""

        ctx["show_all"] = show_all
        ctx["current_filters"] = {
            "q": self.request.GET.get("q", ""),
            "type": self.request.GET.get("type", ""),
            "category": self.request.GET.get("category", ""),
        }
        return ctx


class TransactionCreateView(LoginRequiredMixin, CreateView):
    model = Transaction
    form_class = TransactionForm
    template_name = "transactions/transaction_form.html"
    success_url = reverse_lazy("transactions:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        txn_type = self.request.GET.get("type", "")
        if txn_type in ("income", "expense"):
            initial["type"] = txn_type
        return initial

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Transaction added successfully!")
        return super().form_valid(form)


class TransactionUpdateView(LoginRequiredMixin, UpdateView):
    model = Transaction
    form_class = TransactionForm
    template_name = "transactions/transaction_form.html"
    success_url = reverse_lazy("transactions:list")

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Transaction updated!")
        return super().form_valid(form)


class TransactionDeleteView(LoginRequiredMixin, DeleteView):
    model = Transaction
    template_name = "transactions/transaction_confirm_delete.html"
    success_url = reverse_lazy("transactions:list")

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Transaction deleted.")
        return super().form_valid(form)


class QuickAddView(LoginRequiredMixin, CreateView):
    """AJAX quick-add endpoint."""
    model = Transaction
    form_class = TransactionForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.save()
        return JsonResponse({"success": True})

    def form_invalid(self, form):
        return JsonResponse({"success": False, "errors": form.errors}, status=400)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    template_name = "transactions/category_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return Category.objects.filter(Q(is_system=True) | Q(user=self.request.user))


class CategoryCreateView(LoginRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "transactions/category_form.html"
    success_url = reverse_lazy("transactions:category_list")

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Category created!")
        return super().form_valid(form)


class CategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "transactions/category_form.html"
    success_url = reverse_lazy("transactions:category_list")

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user, is_system=False)


class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = Category
    template_name = "transactions/category_confirm_delete.html"
    success_url = reverse_lazy("transactions:category_list")

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user, is_system=False)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
class BudgetListView(LoginRequiredMixin, ListView):
    model = Budget
    template_name = "transactions/budget_list.html"
    context_object_name = "budgets"

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)


class BudgetCreateView(LoginRequiredMixin, CreateView):
    model = Budget
    form_class = BudgetForm
    template_name = "transactions/budget_form.html"
    success_url = reverse_lazy("transactions:budget_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        # Normalize month to first day
        form.instance.month = form.instance.month.replace(day=1)
        messages.success(self.request, "Budget created!")
        return super().form_valid(form)


class BudgetUpdateView(LoginRequiredMixin, UpdateView):
    model = Budget
    form_class = BudgetForm
    template_name = "transactions/budget_form.html"
    success_url = reverse_lazy("transactions:budget_list")

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class BudgetDeleteView(LoginRequiredMixin, DeleteView):
    model = Budget
    template_name = "transactions/budget_confirm_delete.html"
    success_url = reverse_lazy("transactions:budget_list")

    def get_queryset(self):
        return Budget.objects.filter(user=self.request.user)


# ---------------------------------------------------------------------------
# Savings Goals
# ---------------------------------------------------------------------------
class SavingsListView(LoginRequiredMixin, ListView):
    model = SavingsGoal
    template_name = "transactions/savings_list.html"
    context_object_name = "goals"

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)


class SavingsCreateView(LoginRequiredMixin, CreateView):
    model = SavingsGoal
    form_class = SavingsGoalForm
    template_name = "transactions/savings_form.html"
    success_url = reverse_lazy("transactions:savings_list")

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, "Savings goal created!")
        return super().form_valid(form)


class SavingsUpdateView(LoginRequiredMixin, UpdateView):
    model = SavingsGoal
    form_class = SavingsGoalForm
    template_name = "transactions/savings_form.html"
    success_url = reverse_lazy("transactions:savings_list")

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)


class SavingsDeleteView(LoginRequiredMixin, DeleteView):
    model = SavingsGoal
    template_name = "transactions/savings_confirm_delete.html"
    success_url = reverse_lazy("transactions:savings_list")

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)


class SavingsAddMoneyView(LoginRequiredMixin, View):
    """Add money to a savings goal via POST."""

    def post(self, request, pk):
        goal = get_object_or_404(SavingsGoal, pk=pk, user=request.user)
        amount = request.POST.get("amount", "0")
        try:
            amount = Decimal(amount)
            if amount > 0:
                goal.add_money(amount)
                messages.success(request, f"Added {amount} to {goal.name}!")
            else:
                messages.error(request, "Amount must be positive.")
        except Exception:
            messages.error(request, "Invalid amount.")
        return redirect("transactions:savings_list")
