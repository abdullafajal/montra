"""Management command to seed default categories."""
from django.core.management.base import BaseCommand
from transactions.models import Category


DEFAULT_CATEGORIES = [
    {"name": "Food & Dining", "icon": "restaurant", "color": "#FFB74D"},       # Orange 300
    {"name": "Transportation", "icon": "directions_car", "color": "#64B5F6"},  # Blue 300
    {"name": "Housing", "icon": "home", "color": "#7986CB"},                   # Indigo 300
    {"name": "Entertainment", "icon": "movie", "color": "#F06292"},            # Pink 300
    {"name": "Shopping", "icon": "shopping_bag", "color": "#FF8A65"},          # Deep Orange 300
    {"name": "Healthcare", "icon": "local_hospital", "color": "#E57373"},      # Red 300
    {"name": "Education", "icon": "school", "color": "#4FC3F7"},              # Light Blue 300
    {"name": "Salary", "icon": "payments", "color": "#81C784"},               # Green 300
    {"name": "Freelance", "icon": "work", "color": "#4DB6AC"},                # Teal 300
    {"name": "Investment", "icon": "trending_up", "color": "#AED581"},        # Light Green 300
    {"name": "Gift", "icon": "redeem", "color": "#BA68C8"},                   # Purple 300
    {"name": "Bills & Utilities", "icon": "receipt_long", "color": "#90A4AE"},# Blue Grey 300
    {"name": "Travel", "icon": "flight", "color": "#4DD0E1"},                 # Cyan 300
    {"name": "Clothing", "icon": "checkroom", "color": "#CE93D8"},            # Purple 200
    {"name": "Fitness", "icon": "fitness_center", "color": "#DCE775"},        # Lime 300
    {"name": "Coffee", "icon": "coffee", "color": "#A1887F"},                 # Brown 300
    {"name": "Pets", "icon": "pets", "color": "#BCAAA4"},                     # Brown 200
    {"name": "Other", "icon": "category", "color": "#78909C"},                # Blue Grey 400
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
