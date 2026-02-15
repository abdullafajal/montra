"""Transactions URL configuration."""
from django.urls import path
from . import views

app_name = "transactions"

urlpatterns = [
    # Dashboard
    path("", views.DashboardView.as_view(), name="dashboard"),

    # Transactions
    path("transactions/", views.TransactionListView.as_view(), name="list"),
    path("transactions/add/", views.TransactionCreateView.as_view(), name="create"),
    path("transactions/<int:pk>/edit/", views.TransactionUpdateView.as_view(), name="update"),
    path("transactions/<int:pk>/delete/", views.TransactionDeleteView.as_view(), name="delete"),
    path("transactions/quick-add/", views.QuickAddView.as_view(), name="quick_add"),

    # Categories
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/add/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),

    # Budgets
    path("budgets/", views.BudgetListView.as_view(), name="budget_list"),
    path("budgets/add/", views.BudgetCreateView.as_view(), name="budget_create"),
    path("budgets/<int:pk>/edit/", views.BudgetUpdateView.as_view(), name="budget_update"),
    path("budgets/<int:pk>/delete/", views.BudgetDeleteView.as_view(), name="budget_delete"),

    # Savings Goals
    path("savings/", views.SavingsListView.as_view(), name="savings_list"),
    path("savings/add/", views.SavingsCreateView.as_view(), name="savings_create"),
    path("savings/<int:pk>/edit/", views.SavingsUpdateView.as_view(), name="savings_update"),
    path("savings/<int:pk>/delete/", views.SavingsDeleteView.as_view(), name="savings_delete"),
    path("savings/<int:pk>/add-money/", views.SavingsAddMoneyView.as_view(), name="savings_add_money"),
]
