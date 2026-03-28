# Generated manually — adds BIG_CDRV and MINI_CDRV to the VehicleType choices.
#
# Django's CharField stores the *value* ("BIG_CDRV" / "MINI_CDRV") in the
# database.  The choices list on the model field is purely metadata used by
# forms and the admin for human-readable labels.  No ALTER TABLE is needed;
# Django only needs to record the choices change in the migration graph so
# that `makemigrations` stays clean and future auto-detects remain accurate.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # Must come after the initial fleet table creation
        ("fleet", "0001_initial"),
    ]

    operations = [
        # AlterField updates the choices metadata on the vehicle_type column.
        # The database schema itself does not change — only the Django migration
        # state is updated so that the new choice values are recognised.
        migrations.AlterField(
            model_name="vehicle",
            name="vehicle_type",
            field=models.CharField(
                choices=[
                    ("AMBULANCE", "Ambulance"),
                    ("FIRE", "Fire Truck"),
                    ("JEEP", "Jeep / SUV"),
                    ("MINIBUS", "Mini Bus"),
                    ("MOTO", "Motorcycle"),
                    ("BOAT", "Rescue Boat"),
                    ("TRUCK", "Truck / Lorry"),
                    ("BIG_CDRV", "Big CDRV"),
                    ("MINI_CDRV", "Mini CDRV"),
                    ("OTHER", "Other"),
                ],
                default="OTHER",
                max_length=10,
                verbose_name="Vehicle Type",
            ),
        ),
    ]
