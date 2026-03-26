"""Accounts views — Auth, Profile, Email Verification & Password Reset."""
import threading

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.views import View
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings

from .forms import (
    RegisterForm, LoginForm, ProfileForm,
    ResendVerificationForm, ForgotPasswordForm, SetNewPasswordForm,
)
from .models import UserProfile, EmailVerificationToken, PasswordResetToken


# ---------------------------------------------------------------------------
# Threaded email helper
# ---------------------------------------------------------------------------

def _send_email_async(subject, plain_message, from_email, recipient_list, html_message):
    """Send email in a background thread so the response is instant."""
    thread = threading.Thread(
        target=send_mail,
        args=(subject, plain_message, from_email, recipient_list),
        kwargs={"html_message": html_message, "fail_silently": True},
    )
    thread.daemon = True
    thread.start()


def _send_verification_email(request, user, token):
    """Send a verification email with a link to activate the account."""
    verify_url = request.build_absolute_uri(f"/accounts/verify/{token.token}/")
    subject = "Verify your Espere account"
    html_message = render_to_string("accounts/verify_email.html", {
        "user": user,
        "verify_url": verify_url,
    })
    plain_message = strip_tags(html_message)
    _send_email_async(subject, plain_message, settings.DEFAULT_FROM_EMAIL, [user.email], html_message)


def _send_password_reset_email(request, user, token):
    """Send a password reset email with a link to set a new password."""
    reset_url = request.build_absolute_uri(f"/accounts/reset-password/{token.token}/")
    subject = "Reset your Espere password"
    html_message = render_to_string("accounts/password_reset_email.html", {
        "user": user,
        "reset_url": reset_url,
    })
    plain_message = strip_tags(html_message)
    _send_email_async(subject, plain_message, settings.DEFAULT_FROM_EMAIL, [user.email], html_message)


# ---------------------------------------------------------------------------
# Registration & Verification
# ---------------------------------------------------------------------------

class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/register.html", {"form": RegisterForm()})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            UserProfile.objects.get_or_create(user=user)
            token = EmailVerificationToken.objects.create(user=user)
            _send_verification_email(request, user, token)
            return render(request, "accounts/verification_sent.html", {
                "email": user.email,
            })
        return render(request, "accounts/register.html", {"form": form})


class VerifyEmailView(View):
    def get(self, request, token):
        verification = get_object_or_404(EmailVerificationToken, token=token)
        user = verification.user
        user.is_active = True
        user.save()
        verification.delete()
        # Auto-login after verification
        login(request, user)
        messages.success(request, "Email verified successfully! Welcome to Montra.")
        return redirect("/")


class ResendVerificationView(View):
    def get(self, request):
        return render(request, "accounts/resend_verification.html", {
            "form": ResendVerificationForm(),
            "max_attempts": EmailVerificationToken.MAX_ATTEMPTS,
        })

    def post(self, request):
        form = ResendVerificationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            try:
                user = User.objects.get(email=email, is_active=False)
                token = EmailVerificationToken.objects.filter(user=user).first()

                if token:
                    # Check rate limit
                    if not token.can_resend():
                        remaining = token.get_cooldown_remaining()
                        messages.error(
                            request,
                            f"Too many attempts. Please try again in {remaining}.",
                        )
                        return redirect("accounts:resend_verification")

                    # If cooldown passed, reset attempts
                    if token.attempt_count >= EmailVerificationToken.MAX_ATTEMPTS:
                        token.attempt_count = 0

                    # Regenerate token and increment attempt
                    import uuid
                    token.token = uuid.uuid4()
                    token.attempt_count += 1
                    token.save()
                else:
                    token = EmailVerificationToken.objects.create(user=user)

                _send_verification_email(request, user, token)
                remaining_attempts = EmailVerificationToken.MAX_ATTEMPTS - token.attempt_count
                if remaining_attempts > 0:
                    messages.success(
                        request,
                        f"Verification email sent! {remaining_attempts} attempt(s) remaining.",
                    )
                else:
                    messages.success(
                        request,
                        "Verification email sent! This was your last attempt. "
                        "You'll need to wait 24 hours before requesting again.",
                    )
            except User.DoesNotExist:
                messages.success(
                    request,
                    "If this email is registered, a verification link has been sent.",
                )
            return redirect("accounts:resend_verification")
        return render(request, "accounts/resend_verification.html", {
            "form": form,
            "max_attempts": EmailVerificationToken.MAX_ATTEMPTS,
        })


# ---------------------------------------------------------------------------
# Login & Logout
# ---------------------------------------------------------------------------

class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/login.html", {"form": LoginForm()})

    def post(self, request):
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            messages.success(request, "Welcome back!")
            next_url = request.GET.get("next", "/")
            return redirect(next_url)
        # Check if user exists but is inactive (needs email verification)
        username = request.POST.get("username", "")
        from django.db.models import Q
        user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
        if user and not user.is_active:
            return render(request, "accounts/login.html", {
                "form": form,
                "needs_verification": True,
                "unverified_email": user.email,
            })
        return render(request, "accounts/login.html", {"form": form})


class LogoutView(View):
    def get(self, request):
        logout(request)
        return redirect("/accounts/login/")

    def post(self, request):
        logout(request)
        return redirect("/accounts/login/")


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------

class ForgotPasswordView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/forgot_password.html", {
            "form": ForgotPasswordForm(),
            "max_attempts": PasswordResetToken.MAX_ATTEMPTS,
        })

    def post(self, request):
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(email=email, is_active=True).first()

            if user:
                token = PasswordResetToken.objects.filter(user=user).first()

                if token:
                    # Check rate limit
                    if not token.can_resend():
                        remaining = token.get_cooldown_remaining()
                        messages.error(
                            request,
                            f"Too many attempts. Please try again in {remaining}.",
                        )
                        return redirect("accounts:forgot_password")

                    # If cooldown passed, reset attempts
                    if token.attempt_count >= PasswordResetToken.MAX_ATTEMPTS:
                        token.attempt_count = 0

                    # Regenerate token and increment attempt
                    import uuid
                    token.token = uuid.uuid4()
                    token.attempt_count += 1
                    token.save()
                else:
                    token = PasswordResetToken.objects.create(user=user)

                _send_password_reset_email(request, user, token)

            messages.success(
                request,
                "If this email is registered, a password reset link has been sent.",
            )
            return redirect("accounts:forgot_password")
        return render(request, "accounts/forgot_password.html", {
            "form": form,
            "max_attempts": PasswordResetToken.MAX_ATTEMPTS,
        })


class ResetPasswordConfirmView(View):
    def get(self, request, token):
        reset_token = get_object_or_404(PasswordResetToken, token=token)
        return render(request, "accounts/reset_password_confirm.html", {
            "form": SetNewPasswordForm(),
            "token": token,
        })

    def post(self, request, token):
        reset_token = get_object_or_404(PasswordResetToken, token=token)
        form = SetNewPasswordForm(request.POST)
        if form.is_valid():
            user = reset_token.user
            user.password = make_password(form.cleaned_data["password1"])
            user.save()
            reset_token.delete()
            messages.success(request, "Password reset successful! You can now log in.")
            return redirect("accounts:login")
        return render(request, "accounts/reset_password_confirm.html", {
            "form": form,
            "token": token,
        })


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        form = ProfileForm(instance=profile, user=request.user)
        return render(request, "accounts/profile.html", {"form": form})

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        form = ProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("accounts:profile")
        return render(request, "accounts/profile.html", {"form": form})
