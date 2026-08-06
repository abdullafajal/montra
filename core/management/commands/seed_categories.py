"""Management command to seed default categories."""
from django.core.management.base import BaseCommand
from transactions.models import Category


DEFAULT_CATEGORIES = [
    {"name": "Food & Dining", "icon": "restaurant", "color": "#C8E64A", "type": "expense"},
    {"name": "Transportation", "icon": "directions_car", "color": "#C8E64A", "type": "expense"},
    {"name": "Housing", "icon": "home", "color": "#C8E64A", "type": "expense"},
    {"name": "Entertainment", "icon": "movie", "color": "#C8E64A", "type": "expense"},
    {"name": "Shopping", "icon": "shopping_bag", "color": "#C8E64A", "type": "expense"},
    {"name": "Healthcare", "icon": "local_hospital", "color": "#C8E64A", "type": "expense"},
    {"name": "Education", "icon": "school", "color": "#C8E64A", "type": "expense"},
    {"name": "Salary", "icon": "payments", "color": "#C8E64A", "type": "income"},
    {"name": "Freelance", "icon": "work", "color": "#C8E64A", "type": "income"},
    {"name": "Investment", "icon": "trending_up", "color": "#C8E64A", "type": "income"},
    {"name": "Gift", "icon": "redeem", "color": "#C8E64A", "type": "income"},
    {"name": "Bills & Utilities", "icon": "receipt_long", "color": "#C8E64A", "type": "expense"},
    {"name": "Travel", "icon": "flight", "color": "#C8E64A", "type": "expense"},
    {"name": "Clothing", "icon": "checkroom", "color": "#C8E64A", "type": "expense"},
    {"name": "Fitness", "icon": "fitness_center", "color": "#C8E64A", "type": "expense"},
    {"name": "Coffee", "icon": "coffee", "color": "#C8E64A", "type": "expense"},
    {"name": "Pets", "icon": "pets", "color": "#C8E64A", "type": "expense"},
    {"name": "Other", "icon": "category", "color": "#C8E64A", "type": "expense"},
]


class Command(BaseCommand):
    help = "Seed default categories"

    def handle(self, *args, **kwargs):
        created = 0
        updated = 0
        for cat in DEFAULT_CATEGORIES:
            obj, was_created = Category.objects.get_or_create(
                name=cat["name"],
                is_system=True,
                defaults={"icon": cat["icon"], "color": cat["color"], "type": cat["type"]},
            )
            if was_created:
                created += 1
            else:
                changed = False
                if obj.icon != cat["icon"]:
                    obj.icon = cat["icon"]
                    changed = True
                if obj.color != cat["color"]:
                    obj.color = cat["color"]
                    changed = True
                if getattr(obj, "type", "expense") != cat["type"]:
                    obj.type = cat["type"]
                    changed = True
                if changed:
                    obj.save(update_fields=["icon", "color", "type"])
                    updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} new, updated {updated} existing ({len(DEFAULT_CATEGORIES)} total)."
        ))
