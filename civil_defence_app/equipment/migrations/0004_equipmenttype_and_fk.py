"""
Migration 0004 — Add EquipmentType model and equipment_type FK on Equipment.

What this migration does:
  1. Creates the new `equipment_equipmenttype` table with all fields:
       - name (unique), category, description, scheduled_maintenance_periodicity
       - created_at, updated_at (from TimeStampedModel)
  2. Adds a nullable ForeignKey `equipment_type_id` to the `equipment_equipment`
     table pointing at the new table.

Why nullable FK:
  - 28,263 existing Equipment rows will not have a type assigned yet.
  - The `seed_equipment_types` management command assigns types by matching
    Equipment.name to EquipmentType.name after this migration runs.
  - Once seeded, the FK can be made non-null in a future migration if desired.

Schema change is safe — adding a nullable column requires no data backfill.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("equipment", "0003_equipmentmaintenancelog_is_fit"),
    ]

    operations = [

        # ── Step 1: Create the EquipmentType table ────────────────────────────
        #
        # This is a brand-new table, so Django issues a simple CREATE TABLE.
        # The `scheduled_maintenance_periodicity` default of 1 means monthly
        # checks — the most conservative default for Civil Defence equipment.

        migrations.CreateModel(
            name="EquipmentType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(
                    help_text="Canonical name for this equipment type, e.g. 'Life Jacket with Reflective Panel'.",
                    max_length=200,
                    unique=True,
                    verbose_name="Type Name",
                )),
                ("category", models.CharField(
                    choices=[
                        ("FIRE",  "Fire Fighting"),
                        ("RESCUE","Search & Rescue"),
                        ("MED",  "Medical / First Aid"),
                        ("COMM", "Communication"),
                        ("FLOOD","Flood Relief"),
                        ("PPE",  "Personal Protective Equipment"),
                        ("OTHER","Other"),
                    ],
                    default="OTHER",
                    max_length=8,
                    verbose_name="Category",
                )),
                ("description", models.TextField(
                    blank=True,
                    default="",
                    help_text="What this equipment is used for and key operational notes.",
                    verbose_name="Description",
                )),
                ("scheduled_maintenance_periodicity", models.PositiveIntegerField(
                    default=1,
                    help_text=(
                        "Number of months between scheduled maintenance checks. "
                        "Default: 1 month. The system flags items overdue relative to this value."
                    ),
                    verbose_name="Maintenance Periodicity (months)",
                )),
            ],
            options={
                "verbose_name":        "Equipment Type",
                "verbose_name_plural": "Equipment Types",
                "ordering":            ["category", "name"],
            },
        ),

        # ── Step 2: Add nullable FK on Equipment → EquipmentType ─────────────
        #
        # AddField on a nullable column is a single ALTER TABLE … ADD COLUMN
        # with DEFAULT NULL — no row rewrites, safe on large tables.

        migrations.AddField(
            model_name="equipment",
            name="equipment_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text="The type classification for this physical unit.",
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="equipment_instances",
                to="equipment.equipmenttype",
                verbose_name="Equipment Type",
            ),
        ),
    ]
