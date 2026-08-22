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
