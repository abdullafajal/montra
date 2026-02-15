"""Transactions models — Category, Transaction, Budget."""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Category(models.Model):
    ICON_CHOICES = [
        ("restaurant", "Food"), ("directions_car", "Transport"), ("home", "Housing"),
        ("movie", "Entertainment"), ("shopping_bag", "Shopping"), ("local_hospital", "Healthcare"),
        ("school", "Education"), ("payments", "Salary"), ("work", "Freelance"),
        ("trending_up", "Investment"), ("redeem", "Gift"), ("category", "Other"),
        ("receipt_long", "Bills"), ("flight", "Travel"), ("checkroom", "Clothing"),
        ("fitness_center", "Fitness"), ("pets", "Pets"), ("coffee", "Coffee"),
    ]

    name = models.CharField(max_length=50)
    icon = models.CharField(max_length=30, default="category")
    color = models.CharField(max_length=7, default="#6366f1")  # hex
    is_system = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    TYPE_CHOICES = [
        ("income", "Income"),
        ("expense", "Expense"),
    ]

    PAYMENT_CHOICES = [
        ("cash", "Cash"),
        ("card", "Credit/Debit Card"),
        ("bank", "Bank Transfer"),
        ("upi", "UPI / Mobile Payment"),
        ("other", "Other"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    type = models.CharField(max_length=7, choices=TYPE_CHOICES)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default="cash")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.type}: {self.amount} — {self.category}"


class Budget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="budgets")
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    month = models.DateField(help_text="First day of the budget month")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "category", "month"]
        ordering = ["-month"]

    def __str__(self):
        return f"Budget: {self.category} — {self.amount}"

    def get_spent(self):
        """Get total spent in this category for this month."""
        from django.db.models import Sum
        total = Transaction.objects.filter(
            user=self.user,
            category=self.category,
            type="expense",
            date__year=self.month.year,
            date__month=self.month.month,
        ).aggregate(total=Sum("amount"))["total"]
        return total or 0

    def get_percentage(self):
        spent = float(self.get_spent())
        budget = float(self.amount)
        if budget == 0:
            return 0
        return min(round((spent / budget) * 100, 1), 100)

    def is_exceeded(self):
        return self.get_spent() > self.amount


class SavingsGoal(models.Model):
    ICON_CHOICES = [
        ("savings", "Savings"), ("flag", "Goal"), ("home", "Home"),
        ("flight", "Travel"), ("school", "Education"), ("directions_car", "Car"),
        ("devices", "Tech"), ("favorite", "Wishlist"), ("emergency", "Emergency"),
        ("diamond", "Luxury"), ("volunteer_activism", "Charity"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="savings_goals")
    name = models.CharField(max_length=100)
    target_amount = models.DecimalField(max_digits=12, decimal_places=2)
    current_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    icon = models.CharField(max_length=30, choices=ICON_CHOICES, default="savings")
    color = models.CharField(max_length=7, default="#26A69A")
    deadline = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_completed", "-created_at"]

    def __str__(self):
        return f"{self.name} — {self.current_amount}/{self.target_amount}"

    def get_percentage(self):
        if self.target_amount == 0:
            return 0
        return min(round(float(self.current_amount) / float(self.target_amount) * 100, 1), 100)

    def get_remaining(self):
        remaining = self.target_amount - self.current_amount
        return max(remaining, 0)

    def add_money(self, amount):
        self.current_amount += amount
        if self.current_amount >= self.target_amount:
            self.is_completed = True
        self.save()
