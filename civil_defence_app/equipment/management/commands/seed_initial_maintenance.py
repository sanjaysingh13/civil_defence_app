"""
Management command: seed_initial_maintenance

Usage:
    uv run python manage.py seed_initial_maintenance
    uv run python manage.py seed_initial_maintenance --dry-run

What it does:
  For every Equipment row where:
    • is_functional = True
    • No EquipmentMaintenanceLog exists yet (first-run guard — idempotent)

  Creates one EquipmentMaintenanceLog entry with:
    • check_date      = today's date
    • is_fit          = True
    • status_after_check = "OK" (Functional)
    • checked_by      = None (seeded automatically, no human inspector)
    • remarks         = "Initial status found functional"

  Also updates the Equipment row itself:
    • last_check_date = today
    • next_due_date   = today + scheduled_maintenance_periodicity months
                        (if equipment_type is set; otherwise left null)
    • status          = "OK"

Idempotency:
    Equipment rows that already have at least one EquipmentMaintenanceLog are
    skipped.  Re-running the command will only process genuinely un-logged items.

Run order:
    seed_equipment (creates Equipment rows)
    → seed_equipment_types (creates EquipmentType + links Equipment)
    → THIS COMMAND (seeds initial maintenance logs for functional items)
"""

import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from civil_defence_app.equipment.models import (
    Equipment,
    EquipmentMaintenanceLog,
    EquipmentStatus,
    add_months,
)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

INITIAL_REMARKS = "Initial status found functional"

# We process Equipment rows in this batch size to avoid holding too much data
# in memory.  28,263 rows is manageable, but batching is good practice.
BATCH_SIZE = 500


class Command(BaseCommand):
    """
    Seeds an initial maintenance log entry for every functional Equipment item
    that has not yet been inspected.
    """

    help = (
        "Seed initial EquipmentMaintenanceLog entries for all is_functional=True "
        "equipment that has no existing log. Also sets last_check_date and "
        "next_due_date on the Equipment row."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today   = datetime.date.today()

        self.stdout.write(f"Date      : {today}")
        self.stdout.write(f"Dry run   : {dry_run}\n")

        # ── 1. Find equipment items that need seeding ─────────────────────────
        #
        # We use a subquery-free approach: fetch the PKs of Equipment that
        # already have at least one log, then exclude those from our target set.
        #
        # This avoids a correlated subquery and works well with Django's ORM.

        # Set of Equipment PKs that already have at least one maintenance log.
        already_logged_pks = set(
            EquipmentMaintenanceLog.objects
            .values_list("equipment_id", flat=True)
            .distinct()
        )

        # Target: functional items with no existing log.
        target_qs = (
            Equipment.objects
            .filter(is_functional=True)
            .exclude(pk__in=already_logged_pks)
            .select_related("equipment_type")
            .order_by("id")   # predictable order for batched processing
        )

        total_target = target_qs.count()
        self.stdout.write(f"Functional items with no log : {total_target}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[DRY ] Would create {total_target} EquipmentMaintenanceLog rows\n"
                    f"       and update {total_target} Equipment rows "
                    f"(last_check_date, next_due_date, status)."
                )
            )
            self.stdout.write(self.style.WARNING("DRY RUN — no records written."))
            return

        # ── 2. Seed logs and update equipment in batches ──────────────────────
        #
        # We use bulk_create for the logs (one INSERT per batch instead of one
        # per row) and bulk_update for the equipment fields.
        #
        # transaction.atomic() wraps each batch so a mid-run error leaves the
        # DB in a consistent state (all rows in the batch or none of them).

        logs_to_create:    list[EquipmentMaintenanceLog] = []
        equip_to_update:   list[Equipment]               = []

        created_logs    = 0
        updated_equip   = 0
        error_count     = 0

        self.stdout.write("Seeding maintenance logs …")

        # iterator() fetches rows incrementally from the DB cursor so we
        # don't load all 28k rows into memory at once.
        for equip in target_qs.iterator():
            try:
                # ── Build the maintenance log object (not saved yet) ──────────
                log = EquipmentMaintenanceLog(
                    equipment         = equip,
                    check_date        = today,
                    checked_by        = None,          # seeded automatically
                    is_fit            = True,
                    status_after_check = EquipmentStatus.FUNCTIONAL,
                    remarks           = INITIAL_REMARKS,
                )
                logs_to_create.append(log)

                # ── Update the Equipment fields ───────────────────────────────
                #
                # calculate next_due_date only if the equipment has an associated
                # EquipmentType with a periodicity set; otherwise leave it null.
                equip.last_check_date = today
                equip.status          = EquipmentStatus.FUNCTIONAL

                if equip.equipment_type_id and equip.equipment_type:
                    periodicity = equip.equipment_type.scheduled_maintenance_periodicity
                    # add_months is defined in models.py — handles month-end clamping.
                    equip.next_due_date = add_months(today, periodicity)
                else:
                    # No type assigned → cannot compute next due date.
                    equip.next_due_date = None

                equip_to_update.append(equip)

            except Exception as exc:
                error_count += 1
                self.stderr.write(
                    self.style.ERROR(f"  Error for equipment pk={equip.pk}: {exc}")
                )

            # ── Flush batch to DB ─────────────────────────────────────────────
            if len(logs_to_create) >= BATCH_SIZE:
                with transaction.atomic():
                    EquipmentMaintenanceLog.objects.bulk_create(logs_to_create)
                    Equipment.objects.bulk_update(
                        equip_to_update,
                        ["last_check_date", "next_due_date", "status"],
                    )
                created_logs  += len(logs_to_create)
                updated_equip += len(equip_to_update)
                logs_to_create  = []
                equip_to_update = []

                # Progress indicator for the long-running batch job.
                self.stdout.write(f"  … {created_logs} logs created so far …")

        # ── Flush the final partial batch ─────────────────────────────────────
        if logs_to_create:
            with transaction.atomic():
                EquipmentMaintenanceLog.objects.bulk_create(logs_to_create)
                Equipment.objects.bulk_update(
                    equip_to_update,
                    ["last_check_date", "next_due_date", "status"],
                )
            created_logs  += len(logs_to_create)
            updated_equip += len(equip_to_update)

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write("\n" + "─" * 55)
        self.stdout.write(self.style.SUCCESS(f"  Logs created   : {created_logs:>6}"))
        self.stdout.write(self.style.SUCCESS(f"  Equipment updated: {updated_equip:>6}"))
        if error_count:
            self.stdout.write(self.style.ERROR(f"  Errors         : {error_count:>6}"))
        self.stdout.write("─" * 55)
        self.stdout.write(self.style.SUCCESS("Done."))
