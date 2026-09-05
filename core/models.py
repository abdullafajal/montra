from django.db import models

class ContactMessage(models.Model):
    TYPE_CHOICES = (
        ('bug_report', 'Bug Report'),
        ('support', 'Support'),
        ('feedback', 'Feedback'),
    )
    
    name = models.CharField(max_length=255)
    email = models.EmailField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='support')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_type_display()} from {self.name}"

class AppVersion(models.Model):
    version_code = models.IntegerField(help_text="The internal build number (e.g., 1)")
    version_name = models.CharField(max_length=50, help_text="The display version (e.g., 1.0.0)")
    is_required = models.BooleanField(default=False, help_text="If true, users must update to continue using the app")
    release_notes = models.TextField(default="Bug fixes and performance improvements.", blank=True, help_text="What's new in this version")
    update_url = models.URLField(default="https://espere.in/espere.apk", help_text="The URL to download the new version")
    is_active = models.BooleanField(default=True, help_text="Only the active version with the highest version_code is returned to the app")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version_code']

    def __str__(self):
        return f"v{self.version_name} ({self.version_code})"
