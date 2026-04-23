from django.db import migrations
from django.db import models


def copy_equipment_notes_to_type(apps, schema_editor):
    Equipment = apps.get_model("equipment", "Equipment")
    EquipmentType = apps.get_model("equipment", "EquipmentType")

    for equipment_type in EquipmentType.objects.all().iterator():
        if (equipment_type.equipment_maintainance_note or "").strip():
            continue
        note_row = (
            Equipment.objects.filter(
                equipment_type=equipment_type,
                equipment_maintainance_note__gt="",
            )
            .exclude(equipment_maintainance_note__isnull=True)
            .first()
        )
        if note_row:
            equipment_type.equipment_maintainance_note = (
                note_row.equipment_maintainance_note
            )
            equipment_type.save(update_fields=["equipment_maintainance_note"])


class Migration(migrations.Migration):
    dependencies = [
        ("equipment", "0005_equipment_equipment_maintainance_note_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="equipmenttype",
            name="equipment_maintainance_note",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Reminder notes on what to do during maintenance checks.",
                verbose_name="Equipment Maintainance Note",
            ),
        ),
        migrations.RunPython(
            copy_equipment_notes_to_type,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="equipment",
            name="equipment_maintainance_note",
        ),
    ]
