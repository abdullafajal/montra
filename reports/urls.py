"""Reports URL configuration."""
from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportsView.as_view(), name="reports"),
    path("export/csv/", views.ExportCSVView.as_view(), name="export_csv"),
    path("export/pdf/", views.ExportPDFView.as_view(), name="export_pdf"),
]
