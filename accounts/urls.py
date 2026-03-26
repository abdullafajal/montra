"""Accounts URL configuration."""
from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("verify/<uuid:token>/", views.VerifyEmailView.as_view(), name="verify_email"),
    path("resend-verification/", views.ResendVerificationView.as_view(), name="resend_verification"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="forgot_password"),
    path("reset-password/<uuid:token>/", views.ResetPasswordConfirmView.as_view(), name="reset_password_confirm"),
]
