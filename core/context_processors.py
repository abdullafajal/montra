"""
Core context processors — inject global data into every template.
"""
from accounts.models import UserProfile


def global_context(request):
    """Provide theme and currency to all templates."""
    ctx = {
        "current_currency": "USD",
        "currency_symbol": "$",
        "theme": "light",
    }
    if request.user.is_authenticated:
        try:
            profile = request.user.userprofile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=request.user)
        ctx["current_currency"] = profile.currency
        ctx["currency_symbol"] = profile.get_currency_symbol()
        ctx["theme"] = profile.theme
    return ctx
