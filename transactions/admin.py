from django.contrib import admin
from .models import Transaction, Category, Budget, SavingsGoal

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "icon", "color", "is_system", "user"]
    list_filter = ["is_system"]

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "type", "category", "date", "payment_method"]
    list_filter = ["type", "payment_method", "date"]
    search_fields = ["notes", "category__name"]

@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ["user", "category", "amount", "month"]
    list_filter = ["month"]

@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    list_display = ["user", "name", "target_amount", "current_amount", "is_completed", "deadline"]
    list_filter = ["is_completed"]

