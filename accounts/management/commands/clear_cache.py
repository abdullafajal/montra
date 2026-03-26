from django.core.management.base import BaseCommand
from django.core.cache import cache

class Command(BaseCommand):
    help = "Clears the entire Django cache system (montra_cache_table)"

    def handle(self, *args, **options):
        # Clears everything in the configured cache backend
        cache.clear()
        self.stdout.write(self.style.SUCCESS("✅ Success: The cache has been completely cleared!"))
