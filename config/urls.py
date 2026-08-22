"""
Root URL configuration for Montra.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core.views import assetlinks_view
from split_expense.views import InvitationAcceptSpecialView

urlpatterns = [
    path("backend/admin/", admin.site.urls),
    path("", include("transactions.urls")),
    path("accounts/", include("accounts.urls")),
    path("reports/", include("reports.urls")),
    path("groups/", include("split_expense.urls", namespace='split_expense')),
    path("api/", include("api.urls", namespace='api')),
    path(".well-known/assetlinks.json", assetlinks_view, name="assetlinks"),
    path("invite/<uuid:token>/", InvitationAcceptSpecialView.as_view(), name="invitation_special_link_root"),
    path('', include('pwa.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
