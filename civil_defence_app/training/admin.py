"""Training app — Django Admin configuration."""

from django.contrib import admin

from .models import Training
from .models import TrainingAttendance
from .models import TrainingInstance


# ─────────────────────────────────────────────────────────────────────────────
# INLINE: TrainingInstance nested inside Training detail page
# ─────────────────────────────────────────────────────────────────────────────

class TrainingInstanceInline(admin.TabularInline):
    """
    TabularInline displays related objects as rows inside the parent form.
    Here, TrainingInstances (batches) are shown directly on the Training page.
    """
    model          = TrainingInstance
    extra          = 0        # don't show empty extra rows by default
    fields         = ("unit", "batch_no", "location", "start_date", "end_date", "instructor")
    autocomplete_fields = ("unit",)


# ─────────────────────────────────────────────────────────────────────────────
# INLINE: TrainingAttendance nested inside TrainingInstance detail page
# ─────────────────────────────────────────────────────────────────────────────

class TrainingAttendanceInline(admin.TabularInline):
    """Attendee list shown on each TrainingInstance page."""
    model  = TrainingAttendance
    extra  = 0
    fields = ("volunteer", "certificate_no", "notes")
    autocomplete_fields = ("volunteer",)


@admin.register(Training)
class TrainingAdmin(admin.ModelAdmin):
    list_display   = ("name", "training_type", "instance_count")
    list_filter    = ("training_type",)
    search_fields  = ("name",)
    inlines        = [TrainingInstanceInline]
    readonly_fields = ("created_at", "updated_at")

    def instance_count(self, obj: Training) -> int:
        return obj.instances.count()
    instance_count.short_description = "Batches"  # type: ignore[attr-defined]


@admin.register(TrainingInstance)
class TrainingInstanceAdmin(admin.ModelAdmin):
    list_display   = ("training", "unit", "location", "start_date", "end_date", "instructor")
    list_filter    = ("training", "unit")
    search_fields  = ("location", "batch_no", "instructor")
    autocomplete_fields = ("training", "unit")
    readonly_fields = ("created_at", "updated_at")
    inlines        = [TrainingAttendanceInline]


@admin.register(TrainingAttendance)
class TrainingAttendanceAdmin(admin.ModelAdmin):
    list_display    = ("volunteer", "training_instance", "certificate_no")
    list_filter     = ("training_instance__training",)
    search_fields   = ("volunteer__name", "certificate_no")
    autocomplete_fields = ("volunteer", "training_instance")
    readonly_fields = ("created_at", "updated_at")
