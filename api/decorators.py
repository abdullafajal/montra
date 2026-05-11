"""
Decorators and middleware helpers for API authentication.
"""
import json
from functools import wraps

from django.http import JsonResponse

from .authentication import APIToken


def api_login_required(view_func):
    """Decorator that checks for Bearer token in Authorization header."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse(
                {"error": "Authentication required."},
                status=401,
            )
        token_key = auth_header[7:].strip()
        user = APIToken.get_user_from_token(token_key)
        if user is None:
            return JsonResponse(
                {"error": "Invalid or expired token."},
                status=401,
            )
        request.api_user = user
        return view_func(request, *args, **kwargs)
    return wrapper


def parse_json_body(request):
    """Parse JSON from request body, return dict or empty dict."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}
