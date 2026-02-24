"""Reports views — Analytics, PDF export, CSV export."""
import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView, View
from django.core.cache import cache

from transactions.models import Transaction, Category


class ReportsView(LoginRequiredMixin, TemplateView):
    template_name = "reports/reports.html"

    def get(self, request, *args, **kwargs):
        user = request.user
        today = timezone.now().date()
        year = int(request.GET.get("year", today.year))
        
        context = self.get_context_data(year=year, **kwargs)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.now().date()
        year = kwargs.get("year", today.year)

        # Monthly summary for the year
        monthly_data = []
        for m in range(1, 13):
            txns = Transaction.objects.filter(user=user, date__year=year, date__month=m)
            inc = txns.filter(type="income").aggregate(t=Sum("amount"))["t"] or Decimal("0")
            exp = txns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or Decimal("0")
            monthly_data.append({
                "month": date(year, m, 1).strftime("%b"),
                "income": float(inc),
                "expense": float(exp),
                "expenses": float(exp),
                "savings": float(inc - exp),
                "net": float(inc - exp),
            })

        # Top spending categories this year
        top_cats_qs = (
            Transaction.objects.filter(user=user, type="expense", date__year=year)
            .values("category__name", "category__icon", "category__color")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:10]
        )

        # Compute percentage for each category
        max_total = float(top_cats_qs[0]["total"]) if top_cats_qs else 1
        top_categories = []
        for c in top_cats_qs:
            top_categories.append({
                "name": c["category__name"] or "Other",
                "icon": c["category__icon"] or "category",
                "color": c["category__color"] or "#6366f1",
                "total": float(c["total"]),
                "pct": round(float(c["total"]) / max_total * 100, 1),
            })

        # Yearly totals
        year_income = sum(m["income"] for m in monthly_data)
        year_expense = sum(m["expense"] for m in monthly_data)

        # Chart data
        bar_labels = [m["month"] for m in monthly_data]
        bar_income = [m["income"] for m in monthly_data]
        bar_expense = [m["expense"] for m in monthly_data]

        # Savings trend
        savings_values = []
        running = 0
        for m in monthly_data:
            running += m["savings"]
            savings_values.append(round(running, 2))

        # Pie chart
        pie_labels = [c["name"] for c in top_categories]
        pie_values = [c["total"] for c in top_categories]
        pie_colors = [c["color"] for c in top_categories]

        ctx.update({
            # Template variable names
            "selected_year": year,
            "available_years": list(range(today.year, today.year - 5, -1)),
            "annual_income": year_income,
            "annual_expenses": year_expense,
            "annual_net": year_income - year_expense,
            "monthly_summary": monthly_data,
            "top_categories": top_categories,
            "monthly_labels": json.dumps(bar_labels),
            "monthly_income_data": json.dumps(bar_income),
            "monthly_expense_data": json.dumps(bar_expense),
            "cat_labels": json.dumps(pie_labels),
            "cat_values": json.dumps(pie_values),
            "cat_colors": json.dumps(pie_colors),
            "savings_data": json.dumps(savings_values),
        })
        return ctx

def _filter_by_period(qs, period, today=None):
    """Filter a transaction queryset by a period string."""
    if today is None:
        today = timezone.now().date()
    if period == "1m":
        start = today.replace(day=1)
        return qs.filter(date__date__gte=start), f"{today.strftime('%B %Y')}"
    elif period == "3m":
        start = (today - timedelta(days=90)).replace(day=1)
        return qs.filter(date__date__gte=start), "Last 3 Months"
    elif period == "6m":
        start = (today - timedelta(days=180)).replace(day=1)
        return qs.filter(date__date__gte=start), "Last 6 Months"
    elif period == "1y":
        start = today.replace(month=1, day=1)
        return qs.filter(date__date__gte=start), f"Year {today.year}"
    else:  # "all"
        return qs, "All Time"


class ExportCSVView(LoginRequiredMixin, View):
    def get(self, request):
        period = request.GET.get("period", "all")
        txns = Transaction.objects.filter(
            user=request.user,
        ).select_related("category").order_by("-date")
        txns, _ = _filter_by_period(txns, period)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="montra_transactions.csv"'

        writer = csv.writer(response)
        writer.writerow(["Date", "Time", "Type", "Category", "Amount", "Payment Method", "Notes"])
        for t in txns:
            writer.writerow([
                t.date.strftime("%Y-%m-%d"),
                t.date.strftime("%H:%M"),
                t.type.title(),
                str(t.category) if t.category else "—",
                str(t.amount),
                t.get_payment_method_display(),
                t.notes,
            ])
        return response


class ExportPDFView(LoginRequiredMixin, View):
    # Project theme colors (Montra Bold Light)
    BG_COLOR = "#FFFFFF"       # Main page background
    SURFACE = "#F4F4F5"        # Card / Table background
    PRIMARY = "#0F0F0F"        # App Black
    BORDER = "#E4E4E7"         # Borders / dividers
    TEXT_DARK = "#18181B"      # Main dark text
    TEXT_MUTED = "#71717A"     # Muted text
    INCOME_COLOR = "#C8E64A"   # App Green
    EXPENSE_COLOR = "#EF4444"  # Modern Red
    ACCENT = "#C8E64A"         # App Green

    def get(self, request):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
        )

        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from django.conf import settings
        import os

        try:
            font_dir = os.path.join(settings.BASE_DIR, "static", "fonts")
            pdfmetrics.registerFont(TTFont("NotoSans", os.path.join(font_dir, "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("NotoSans-Bold", os.path.join(font_dir, "NotoSans-Bold.ttf")))
            FONT_REGULAR = "NotoSans"
            FONT_BOLD = "NotoSans-Bold"
        except Exception:
            FONT_REGULAR = "Helvetica"
            FONT_BOLD = "Helvetica-Bold"

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            topMargin=1.0 * inch, bottomMargin=1.0 * inch,
            leftMargin=0.8 * inch, rightMargin=0.8 * inch,
        )
        styles = getSampleStyleSheet()
        elements = []

        # Custom styles for smaller, cleaner look
        title_style = ParagraphStyle(
            "MontraTitle", parent=styles["Title"],
            fontSize=24, textColor=colors.HexColor(self.PRIMARY),
            fontName=FONT_BOLD,
            spaceAfter=6,
            alignment=TA_LEFT,
        )
        subtitle_style = ParagraphStyle(
            "MontraSubtitle", parent=styles["Normal"],
            fontSize=10, textColor=colors.HexColor("#A1A1AA"),
            fontName=FONT_REGULAR,
            spaceAfter=2,
            alignment=TA_LEFT,
        )
        heading_style = ParagraphStyle(
            "MontraHeading", parent=styles["Heading2"],
            fontSize=13, textColor=colors.HexColor(self.TEXT_DARK),
            fontName=FONT_BOLD,
            spaceBefore=20, spaceAfter=8,
        )
        normal_style = ParagraphStyle(
            "NormalDark", parent=styles["Normal"],
            textColor=colors.HexColor(self.TEXT_DARK),
            fontName=FONT_REGULAR,
            fontSize=10,
            spaceAfter=2,
        )

        # --- Header ---
        user = request.user
        today = timezone.now().date()
        elements.append(Paragraph("Montra.", title_style))
        elements.append(Paragraph("Financial Report", subtitle_style))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(HRFlowable(
            width="100%", thickness=2,
            color=colors.HexColor(self.PRIMARY), spaceAfter=12,
        ))

        name = user.get_full_name() or user.username
        elements.append(Paragraph(f"Prepared for: <b>{name}</b>", normal_style))
        elements.append(Paragraph(
            f"Generated on: {today.strftime('%B %d, %Y')}",
            subtitle_style,
        ))
        elements.append(Spacer(1, 0.25 * inch))

        # --- Period-based filtering ---
        period = request.GET.get("period", "1m")
        txns = Transaction.objects.filter(user=user).select_related("category")
        txns, period_label = _filter_by_period(txns, period, today)

        # Get User's Currency Symbol
        sym = "$"
        if hasattr(user, 'userprofile'):
            sym = user.userprofile.get_currency_symbol()

        income = txns.filter(type="income").aggregate(t=Sum("amount"))["t"] or 0
        expense = txns.filter(type="expense").aggregate(t=Sum("amount"))["t"] or 0
        savings = income - expense

        elements.append(Paragraph(f"Summary — {period_label}", heading_style))

        savings_color = self.INCOME_COLOR if savings >= 0 else self.EXPENSE_COLOR

        summary_data = [
            ["Income", "Expenses", "Net Savings"],
            [f"{sym}{income:,.2f}", f"{sym}{expense:,.2f}", f"{sym}{savings:,.2f}"],
        ]
        
        # 3 columns, spanning 6.67 inches total
        col_w = 2.22 * inch 
        summary_table = Table(summary_data, colWidths=[col_w] * 3)
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(self.PRIMARY)), 
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#D4D4D8")),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("FONTNAME", (0, 1), (-1, 1), FONT_BOLD),
            ("FONTSIZE", (0, 1), (-1, 1), 16),
            ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor(self.INCOME_COLOR)), 
            ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor(self.EXPENSE_COLOR)), 
            ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor(savings_color)),                        
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.3 * inch))

        # --- Transactions table ---
        elements.append(Paragraph(f"Transactions — {period_label}", heading_style))
        data = [["Date", "Time", "Type", "Category", "Amount", "Payment"]]
        for t in txns.order_by("-date")[:100]:
            data.append([
                t.date.strftime("%b %d, %Y"),
                t.date.strftime("%I:%M %p"),
                t.type.title(),
                str(t.category) if t.category else "—",
                f"{sym}{t.amount:,.2f}",
                t.get_payment_method_display(),
            ])

        # Optimize column widths to fit ~6.67 inches
        col_widths = [1.05 * inch, 0.8 * inch, 0.8 * inch, 1.62 * inch, 1.0 * inch, 1.4 * inch]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(self.PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(self.ACCENT)),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, 0), 9.5),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            
            # Alignments 
            ("ALIGN", (0, 0), (3, -1), "LEFT"),
            ("ALIGN", (4, 0), (4, -1), "RIGHT"),
            ("ALIGN", (5, 0), (5, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            # Body rows
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(self.TEXT_DARK)),
            ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("TOPPADDING", (0, 1), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
            
            # Backgrounds
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(self.BG_COLOR)),
            
            # Grid
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor(self.BORDER)),
            ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.HexColor(self.PRIMARY)),
        ]))
        elements.append(table)

        # --- Footer ---
        elements.append(Spacer(1, 0.4 * inch))
        elements.append(HRFlowable(
            width="100%", thickness=1.0,
            color=colors.HexColor(self.BORDER), spaceAfter=8,
        ))
        footer_style = ParagraphStyle(
            "Footer", parent=styles["Normal"],
            fontSize=9, textColor=colors.HexColor(self.TEXT_MUTED),
            alignment=TA_CENTER,
        )
        elements.append(Paragraph(
            f"Montra Financial Tracker · Generated {today.strftime('%b %d, %Y')}",
            footer_style,
        ))

        def draw_bg(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor(self.BG_COLOR))
            # Draw a rectangle filling the entire A4 canvas
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
            canvas.restoreState()

        doc.build(elements, onFirstPage=draw_bg, onLaterPages=draw_bg)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="montra_report.pdf"'
        return response

