from django.core.management.base import BaseCommand
from django.conf import settings
from PIL import Image, ImageDraw
import os

class Command(BaseCommand):
    help = 'Generate PWA icons from source image'

    def handle(self, *args, **options):
        source_path = os.path.join(settings.BASE_DIR, 'static/images/logo.png')
        output_dir = os.path.join(settings.BASE_DIR, 'static/images/icons')

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            self.stdout.write(self.style.SUCCESS(f'Created directory {output_dir}'))

        if not os.path.exists(source_path):
            self.stdout.write(self.style.ERROR(f'Source image not found at {source_path}'))
            return

        img = Image.open(source_path)

        # Standard sizes for PWA
        sizes = [
            (72, 72),
            (96, 96),
            (128, 128),
            (144, 144),
            (152, 152),
            (192, 192),
            (384, 384),
            (512, 512),
            # iOS
            (120, 120),
            (180, 180),
            # Favicons
            (16, 16),
            (32, 32),
        ]

        # Get theme color from settings or default to white
        theme_color = getattr(settings, 'PWA_APP_THEME_COLOR', '#ffffff')

        for width, height in sizes:
            filename = f'icon-{width}x{height}.png'
            dest_path = os.path.join(output_dir, filename)
            
            # Create base image with theme color background
            icon = Image.new('RGBA', (width, height), theme_color)
            
            # Resize source image to fit (maintain aspect ratio, center crop/fit logic?)
            # If we want full bleed icon, we should resize to COVER.
            # But logo usually fits INSIDE.
            # However, looking at the screenshot, the logo seems to have its own background that matches theme.
            # Let's try simple resize first.
            
            # New logic: Resize source to cover the dimension if it's square, or fit if not.
            # Since source is 2000x2000 (square), simple resize works perfectly.
            # If source has transparency, we composited it on theme_color.
            
            resized_source = img.resize((width, height), Image.Resampling.LANCZOS)
            
            # If source has transparency, paste it over the theme background
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                icon.paste(resized_source, (0, 0), resized_source)
            else:
                icon = resized_source.convert('RGBA')
            
            # Ensure no transparency remains for iOS (convert to RGB saves as png without alpha if we verify?)
            # iOS handles PNG alpha by making it black. PWA icons should ideally differ.
            # But let's stick to simple resize + background.
            
            icon.save(dest_path)
            
            self.stdout.write(self.style.SUCCESS(f'Generated {filename}'))

        self.stdout.write(self.style.SUCCESS('All icons generated successfully!'))
