"""API URL configuration for Espere."""
from django.urls import path
from . import views
from .views import GoogleLoginAPIView
from core.views import ContactCaptchaAPIView, ContactSubmitAPIView

app_name = "api"

urlpatterns = [
    # Auth
    path("auth/login/", views.LoginAPIView.as_view(), name="login"),
    path("auth/google/", GoogleLoginAPIView.as_view(), name="google_login"),
    path("auth/logout/", views.LogoutAPIView.as_view(), name="logout"),
    path("auth/register/", views.RegisterAPIView.as_view(), name="register"),
    path("auth/verify-otp/", views.VerifyOTPAPIView.as_view(), name="verify_otp"),
    path("auth/resend-otp/", views.ResendOTPAPIView.as_view(), name="resend_otp"),
    path("auth/profile/", views.ProfileAPIView.as_view(), name="profile"),
    path("auth/profile/avatar/", views.AvatarUploadAPIView.as_view(), name="avatar_upload"),
    path("auth/password/change/", views.ChangePasswordAPIView.as_view(), name="change_password"),
    path("auth/forgot-password/", views.ForgotPasswordAPIView.as_view(), name="forgot_password"),
    path("auth/verify-password-reset-otp/", views.VerifyPasswordResetOTPAPIView.as_view(), name="verify_password_reset_otp"),
    path("auth/reset-password/", views.ResetPasswordAPIView.as_view(), name="reset_password"),

    path("devices/register/", views.DeviceTokenAPIView.as_view(), name="device_register"),
    
    # Contact & Bug Reports
    path("contact/captcha/", ContactCaptchaAPIView.as_view(), name="contact_captcha"),
    path("contact/submit/", ContactSubmitAPIView.as_view(), name="contact_submit"),

    # Dashboard & Reports
    path("dashboard/", views.DashboardAPIView.as_view(), name="dashboard"),
    path("reports/", views.ReportAPIView.as_view(), name="reports"),

    # Transactions
    path("transactions/", views.TransactionListAPIView.as_view(), name="transaction_list"),
    path("transactions/<int:pk>/", views.TransactionDetailAPIView.as_view(), name="transaction_detail"),

    # Categories
    path("categories/", views.CategoryListAPIView.as_view(), name="category_list"),
    path("categories/<int:pk>/", views.CategoryDetailAPIView.as_view(), name="category_detail"),

    # Budgets
    path("budgets/", views.BudgetListAPIView.as_view(), name="budget_list"),
    path("budgets/<int:pk>/", views.BudgetDetailAPIView.as_view(), name="budget_detail"),

    # Savings
    path("savings/", views.SavingsListAPIView.as_view(), name="savings_list"),
    path("savings/<int:pk>/", views.SavingsDetailAPIView.as_view(), name="savings_detail"),
    path("savings/<int:pk>/add-money/", views.SavingsAddMoneyAPIView.as_view(), name="savings_add_money"),

    # Split
    path("split/groups/", views.SplitGroupListAPIView.as_view(), name="split_group_list"),
    path("split/groups/<int:pk>/", views.SplitGroupDetailAPIView.as_view(), name="split_group_detail"),
    path("split/groups/<int:pk>/expenses/", views.SplitExpenseCreateAPIView.as_view(), name="split_expense_create"),
    path("split/groups/<int:group_pk>/expenses/<int:pk>/", views.SplitExpenseDetailAPIView.as_view(), name="split_expense_detail"),
    path("split/groups/<int:pk>/settle/", views.SplitSettleAPIView.as_view(), name="split_settle"),
    path("split/groups/<int:pk>/members/", views.SplitAddMemberAPIView.as_view(), name="split_add_member"),
    path("split/groups/<int:pk>/leave/", views.SplitLeaveGroupAPIView.as_view(), name="split_leave_group"),
    path("split/groups/<int:pk>/remind/", views.SplitReminderAPIView.as_view(), name="split_remind"),
    path("split/users/search/", views.SplitUserSearchAPIView.as_view(), name="split_user_search"),
    
    # Friends
    path("split/friends/", views.SplitFriendListAPIView.as_view(), name="split_friend_list"),
    path("split/friends/action/", views.SplitFriendActionAPIView.as_view(), name="split_friend_action"),
    path("split/invitations/", views.SplitInvitationListAPIView.as_view(), name="split_invitation_list"),
    path("split/invitations/<int:pk>/action/", views.SplitInvitationActionAPIView.as_view(), name="split_invitation_action"),
    path("split/invite/<uuid:token>/", views.SplitTokenInviteAPIView.as_view(), name="split_token_invite"),
]
