# Generated manually — adds the is_fit boolean to EquipmentMaintenanceLog.
#
# BooleanField(default=True) is safe to add: Django issues ALTER TABLE … ADD COLUMN
# with a DEFAULT clause so all pre-existing log rows default to "fit".

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("equipment", "0002_equipment_is_functional"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipmentmaintenancelog",
            name="is_fit",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Check if the equipment is fit for service after this inspection. "
                    "Saving the log will update the equipment's functional status."
                ),
                verbose_name="Equipment is Fit",
            ),
        ),
        # Keep __str__ readable: update verbose_name to match new wording
        migrations.AlterModelOptions(
            name="equipmentmaintenancelog",
            options={
                "ordering": ["-check_date"],
                "verbose_name": "Equipment Maintenance Log",
                "verbose_name_plural": "Equipment Maintenance Logs",
            },
        ),
    ]
