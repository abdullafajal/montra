"""Management command to seed default categories."""
from django.core.management.base import BaseCommand
from transactions.models import Category


DEFAULT_CATEGORIES = [
    {"name": "Food & Dining", "icon": "restaurant", "color": "#C8E64A"},
    {"name": "Transportation", "icon": "directions_car", "color": "#C8E64A"},
    {"name": "Housing", "icon": "home", "color": "#C8E64A"},
    {"name": "Entertainment", "icon": "movie", "color": "#C8E64A"},
    {"name": "Shopping", "icon": "shopping_bag", "color": "#C8E64A"},
    {"name": "Healthcare", "icon": "local_hospital", "color": "#C8E64A"},
    {"name": "Education", "icon": "school", "color": "#C8E64A"},
    {"name": "Salary", "icon": "payments", "color": "#C8E64A"},
    {"name": "Freelance", "icon": "work", "color": "#C8E64A"},
    {"name": "Investment", "icon": "trending_up", "color": "#C8E64A"},
    {"name": "Gift", "icon": "redeem", "color": "#C8E64A"},
    {"name": "Bills & Utilities", "icon": "receipt_long", "color": "#C8E64A"},
    {"name": "Travel", "icon": "flight", "color": "#C8E64A"},
    {"name": "Clothing", "icon": "checkroom", "color": "#C8E64A"},
    {"name": "Fitness", "icon": "fitness_center", "color": "#C8E64A"},
    {"name": "Coffee", "icon": "coffee", "color": "#C8E64A"},
    {"name": "Pets", "icon": "pets", "color": "#C8E64A"},
    {"name": "Other", "icon": "category", "color": "#C8E64A"},
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
                defaults={"icon": cat["icon"], "color": cat["color"]},
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
                if changed:
                    obj.save(update_fields=["icon", "color"])
                    updated += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} new, updated {updated} existing ({len(DEFAULT_CATEGORIES)} total)."
        ))
