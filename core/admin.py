from django.contrib import admin

from .models import ContactMessage, AppVersion

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'type', 'created_at')
    list_filter = ('type', 'created_at')
    search_fields = ('name', 'email', 'message')

@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = ('version_name', 'version_code', 'is_required', 'is_active', 'created_at')
    list_filter = ('is_required', 'is_active')
    search_fields = ('version_name', 'release_notes')
