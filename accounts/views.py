"""Accounts views — Auth & Profile."""
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    PasswordResetView, PasswordResetDoneView,
    PasswordResetConfirmView, PasswordResetCompleteView,
)
from django.views import View
from django.views.generic import UpdateView
from django.urls import reverse_lazy
from django.contrib import messages

from .forms import RegisterForm, LoginForm, ProfileForm
from .models import UserProfile


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/register.html", {"form": RegisterForm()})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
            login(request, user)
            messages.success(request, "Welcome! Your account has been created.")
            return redirect("/")
        return render(request, "accounts/register.html", {"form": form})


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
        return render(request, "accounts/login.html", {"form": form})


class LogoutView(View):
    def get(self, request):
        logout(request)
        return redirect("/accounts/login/")

    def post(self, request):
        logout(request)
        return redirect("/accounts/login/")


class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        form = ProfileForm(instance=profile, user=request.user)
        return render(request, "accounts/profile.html", {"form": form})

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        form = ProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect("accounts:profile")
        return render(request, "accounts/profile.html", {"form": form})
