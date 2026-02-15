"""Accounts models — UserProfile for preferences."""
from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    CURRENCY_CHOICES = [
        ("USD", "US Dollar ($)"),
        ("EUR", "Euro (€)"),
        ("GBP", "British Pound (£)"),
        ("INR", "Indian Rupee (₹)"),
        ("JPY", "Japanese Yen (¥)"),
        ("CAD", "Canadian Dollar (C$)"),
        ("AUD", "Australian Dollar (A$)"),
        ("PKR", "Pakistani Rupee (Rs)"),
    ]

    THEME_CHOICES = [
        ("light", "Light"),
        ("dark", "Dark"),
    ]

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

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="light")
    created_at = models.DateTimeField(auto_now_add=True)

    def get_currency_symbol(self):
        return self.CURRENCY_SYMBOLS.get(self.currency, "$")

    def __str__(self):
        return f"{self.user.username}'s Profile"
