from django.contrib import admin
from .models import UserProfile, EmailVerificationToken, PasswordResetToken

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "currency", "theme", "email_reminders", "created_at")
    search_fields = ("user__username", "user__email")
    list_filter = ("currency", "theme", "email_reminders")

@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "token", "attempt_count", "last_sent_at", "created_at")
    search_fields = ("user__username", "user__email", "token")
    list_filter = ("attempt_count",)
    readonly_fields = ("token",)

@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "token", "attempt_count", "last_sent_at", "created_at")
    search_fields = ("user__username", "user__email", "token")
    list_filter = ("attempt_count",)
    readonly_fields = ("token",)
