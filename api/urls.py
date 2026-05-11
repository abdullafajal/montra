"""API URL configuration for Espere."""
from django.urls import path
from . import views

app_name = "api"

urlpatterns = [
    # Auth
    path("auth/login/", views.LoginAPIView.as_view(), name="login"),
    path("auth/register/", views.RegisterAPIView.as_view(), name="register"),
    path("auth/profile/", views.ProfileAPIView.as_view(), name="profile"),

    path("devices/register/", views.DeviceTokenAPIView.as_view(), name="device_register"),

    # Dashboard
    path("dashboard/", views.DashboardAPIView.as_view(), name="dashboard"),

    # Transactions
    path("transactions/", views.TransactionListAPIView.as_view(), name="transaction_list"),
    path("transactions/<int:pk>/", views.TransactionDetailAPIView.as_view(), name="transaction_detail"),

    # Categories
    path("categories/", views.CategoryListAPIView.as_view(), name="category_list"),
    path("categories/<int:pk>/", views.CategoryDetailAPIView.as_view(), name="category_detail"),

    # Budgets
    path("budgets/", views.BudgetListAPIView.as_view(), name="budget_list"),

    # Savings
    path("savings/", views.SavingsListAPIView.as_view(), name="savings_list"),
    path("savings/<int:pk>/add-money/", views.SavingsAddMoneyAPIView.as_view(), name="savings_add_money"),

    # Split
    path("split/groups/", views.SplitGroupListAPIView.as_view(), name="split_group_list"),
    path("split/groups/<int:pk>/", views.SplitGroupDetailAPIView.as_view(), name="split_group_detail"),
    path("split/groups/<int:pk>/expenses/", views.SplitExpenseCreateAPIView.as_view(), name="split_expense_create"),
    path("split/groups/<int:pk>/settle/", views.SplitSettleAPIView.as_view(), name="split_settle"),
    path("split/groups/<int:pk>/members/", views.SplitAddMemberAPIView.as_view(), name="split_add_member"),
    path("split/groups/<int:pk>/remind/", views.SplitReminderAPIView.as_view(), name="split_remind"),
    path("split/users/search/", views.SplitUserSearchAPIView.as_view(), name="split_user_search"),
]
