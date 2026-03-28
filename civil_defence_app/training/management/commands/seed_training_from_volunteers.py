"""
Management command: seed_training_from_volunteers

Usage:
    uv run python manage.py seed_training_from_volunteers
    uv run python manage.py seed_training_from_volunteers --dry-run

Steps:
  1. Ensure canonical Training rows exist (Civil Defence Basic Training +
     five special programmes matching parsers.SPECIAL_TOKEN_TO_TRAINING_NAME).
  2. For each Volunteer with parseable basic_training_details:
       get_or_create a TrainingInstance (Basic programme, venue, dates, unit)
       get_or_create TrainingAttendance(volunteer, instance).
  3. For each token in parsed special_training_details:
       get_or_create an undated TrainingInstance per (programme, unit)
       with batch_no IMPORT-U<unit_id>-T<training_id>
       get_or_create TrainingAttendance.

Idempotent:
  Attendance rows use get_or_create on (volunteer, training_instance).
  Instances use stable lookup keys so re-runs attach to the same batch rows.

Does not delete or modify legacy basic_training_details / special_training_details
text fields — they remain the audit trail.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from civil_defence_app.personnel.models import Volunteer
from civil_defence_app.training.models import Training, TrainingAttendance, TrainingInstance
from civil_defence_app.training.parsers import (
    canonical_training_specs,
    parse_basic_training_details,
    parse_special_training_details,
)


class Command(BaseCommand):
    help = "Link volunteers to TrainingInstance + TrainingAttendance from legacy text fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute statistics without writing to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process at most N volunteers (for debugging).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit   = options["limit"]

        self.stdout.write(f"Dry run: {dry_run}")
        # Note: `if limit:` would wrongly treat 0 as "no limit" — use `is not None`.
        if limit is not None:
            self.stdout.write(f"Limit:   {limit} volunteers\n")

        # ── 1. Canonical programmes ─────────────────────────────────────────
        basic_training: Training | None = None
        for spec in canonical_training_specs():
            if dry_run:
                self.stdout.write(f"  [DRY ] would ensure Training: {spec['name']}")
                continue
            _t, created = Training.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "training_type": spec["training_type"],
                    "description":   spec["description"],
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  Created Training: {spec['name']}"))

        if not dry_run:
            basic_training = Training.objects.get(name="Civil Defence Basic Training")

        stats = {
            "volunteers_scanned":      0,
            "basic_parsed":            0,
            "basic_skipped_unparsed": 0,
            "basic_attendance_created": 0,
            "basic_attendance_exists":  0,
            "special_tokens":         0,
            "special_attendance_created": 0,
            "special_attendance_exists":  0,
        }

        qs = Volunteer.objects.all().order_by("pk")
        if limit is not None:
            qs = qs[:limit]

        for vol in qs.iterator(chunk_size=500):
            stats["volunteers_scanned"] += 1

            if dry_run:
                parsed = parse_basic_training_details(vol.basic_training_details or "")
                if parsed:
                    stats["basic_parsed"] += 1
                elif (vol.basic_training_details or "").strip():
                    stats["basic_skipped_unparsed"] += 1
                names = parse_special_training_details(vol.special_training_details or "")
                stats["special_tokens"] += len(names)
                continue

            with transaction.atomic():
                # ── Basic ────────────────────────────────────────────────
                b = parse_basic_training_details(vol.basic_training_details or "")
                if b:
                    stats["basic_parsed"] += 1
                    inst, _ = TrainingInstance.objects.get_or_create(
                        training=basic_training,
                        unit=vol.unit,
                        start_date=b["start_date"],
                        end_date=b["end_date"],
                        location=b["location"][:255],
                        defaults={
                            "batch_no": "",
                            "notes":    "Imported from volunteer basic_training_details (seed_training_from_volunteers).",
                        },
                    )
                    att, c = TrainingAttendance.objects.get_or_create(
                        volunteer=vol,
                        training_instance=inst,
                        defaults={"notes": "Linked from legacy basic_training_details text."},
                    )
                    if c:
                        stats["basic_attendance_created"] += 1
                    else:
                        stats["basic_attendance_exists"] += 1
                elif (vol.basic_training_details or "").strip():
                    stats["basic_skipped_unparsed"] += 1

                # ── Special ──────────────────────────────────────────────
                for prog_name in parse_special_training_details(vol.special_training_details or ""):
                    stats["special_tokens"] += 1
                    tr = Training.objects.filter(name=prog_name).first()
                    if not tr:
                        self.stderr.write(self.style.WARNING(f"  Missing Training row: {prog_name}"))
                        continue
                    batch_no = f"IMPORT-U{vol.unit_id}-T{tr.pk}"
                    inst, _ = TrainingInstance.objects.get_or_create(
                        training=tr,
                        unit=vol.unit,
                        batch_no=batch_no[:100],
                        defaults={
                            "location":   "",
                            "start_date": None,
                            "end_date":   None,
                            "notes":      "Imported from volunteer special_training_details; dates not in source.",
                        },
                    )
                    att, c = TrainingAttendance.objects.get_or_create(
                        volunteer=vol,
                        training_instance=inst,
                        defaults={"notes": "Linked from legacy special_training_details text."},
                    )
                    if c:
                        stats["special_attendance_created"] += 1
                    else:
                        stats["special_attendance_exists"] += 1

        self.stdout.write("\n" + "─" * 55)
        for k, v in stats.items():
            self.stdout.write(f"  {k}: {v}")
        self.stdout.write("─" * 55)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no database writes."))
        else:
            self.stdout.write(self.style.SUCCESS("Done."))
