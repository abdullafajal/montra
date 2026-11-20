from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("split_expense", "0012_alter_group_invite_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="category",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
