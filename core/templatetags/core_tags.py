from django import template

register = template.Library()


CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "JPY": "¥",
    "CAD": "C$",
    "AUD": "A$",
    "PKR": "Rs",
}


@register.filter
def currency(value, symbol="$"):
    """Format a number as currency."""
    try:
        val = float(value)
        if val < 0:
            return f"-{symbol}{abs(val):,.2f}"
        return f"{symbol}{val:,.2f}"
    except (ValueError, TypeError):
        return value


@register.filter
def percentage(value, total):
    """Calculate percentage."""
    try:
        if float(total) == 0:
            return "0"
        return f"{(float(value) / float(total)) * 100:.1f}"
    except (ValueError, TypeError, ZeroDivisionError):
        return "0"


@register.filter
def abs_value(value):
    """Return absolute value."""
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return value


@register.simple_tag
def active_nav(request, pattern, active_class=None, inactive_class=None):
    """Return M3-style active/inactive CSS classes for navigation items."""
    import re
    is_active = bool(re.search(pattern, request.path))

    if active_class is not None:
        # Custom class mode: return active_class if match, else inactive_class
        return active_class if is_active else (inactive_class or "")

    # Default M3 nav styling
    if is_active:
        return "nav-item-active text-m3-on-primary-container dark:text-m3-on-primary-container-dark"
    return "text-m3-on-surface dark:text-m3-on-surface-dark hover:bg-m3-surface-container-high dark:hover:bg-m3-surface-container-high-dark"
