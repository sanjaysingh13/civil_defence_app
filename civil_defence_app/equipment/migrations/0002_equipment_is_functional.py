# Generated manually — adds the is_functional boolean field to Equipment.
#
# BooleanField with default=True is safe to add to an existing table on
# both SQLite and PostgreSQL: Django issues ALTER TABLE … ADD COLUMN with a
# DEFAULT clause so every pre-existing row gets True automatically.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # Must run after the initial table creation
        ("equipment", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipment",
            name="is_functional",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "True if this specific item is currently in working order. "
                    "False means it is non-functional / under repair."
                ),
                verbose_name="Is Functional",
            ),
        ),
    ]
