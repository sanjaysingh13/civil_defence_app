"""
Personnel app — Django Admin configuration.

Django's admin site is an auto-generated UI that lets authorised staff
browse, search, filter, create, edit and delete database records.

We customise it here by:
  - list_display  : columns shown in the list/table view
  - list_filter   : sidebar filter checkboxes
  - search_fields : powers the search bar (uses icontains under the hood)
  - readonly_fields : fields shown but not editable in the detail form
  - raw_id_fields / autocomplete_fields : for FK fields that could have
    thousands of choices (avoids a slow giant <select> dropdown)

Register a model with admin.site.register(Model, AdminClass) or the
@admin.register(Model) decorator.
"""

from django.contrib import admin

from .models import OfficeDutyMonthSubmission
from .models import OfficeDutyPeriod
from .models import Unit
from .models import Volunteer
from .models import VolunteerOfficeDutyMonth

# ─────────────────────────────────────────────────────────────────────────────
# UNIT ADMIN
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    """Admin config for the Unit (district) model."""

    # Columns shown in the changelist table.
    list_display = ("name", "slug", "volunteer_count", "created_at")

    # Fields the search bar queries.  The ^ prefix means startswith,
    # = means exact, @ means full-text, no prefix means icontains.
    search_fields = ("name", "slug")

    # auto-populate slug from name when creating
    prepopulated_fields = {"slug": ("name",)}

    # Read-only timestamps
    readonly_fields = ("created_at", "updated_at")

    @admin.display(
        description="Active Volunteers",
    )
    def volunteer_count(self, obj: Unit) -> int:
        """Custom column: count of active volunteers in this unit."""
        return obj.volunteers.filter(is_active=True).count()


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER ADMIN
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Volunteer)
class VolunteerAdmin(admin.ModelAdmin):
    """Admin config for the Volunteer model."""

    list_display = (
        "name",
        "serial_no",
        "unit",
        "block",
        "gender",
        "category",
        "blood_group",
        "mobile",
        "registration_date",
        "is_active",
    )

    list_filter = (
        "unit",
        "gender",
        "category",
        "blood_group",
        "is_active",
        "swasthya_sathi",
    )

    search_fields = ("name", "aadhar_no", "hrms_id", "mobile", "email", "serial_no")

    readonly_fields = ("created_at", "updated_at")

    # autocomplete_fields uses the search_fields defined in UnitAdmin to provide
    # a live-search widget instead of a huge dropdown.
    autocomplete_fields = ("unit",)

    # Organise the detail form into logical sections using fieldsets.
    # Each tuple is (section_title, {fields: [...]}).
    fieldsets = (
        (
            "Organisational",
            {
                "fields": (
                    "unit",
                    "serial_no",
                    "block",
                    "is_active",
                    "derostered_on",
                    "deroster_reason",
                ),
            },
        ),
        (
            "Personal Information",
            {
                "fields": (
                    "name",
                    "gender",
                    "category",
                    "blood_group",
                    "dob",
                    "date_60",
                ),
            },
        ),
        (
            "Contact",
            {
                "fields": ("mobile", "email", "guardian_address"),
            },
        ),
        (
            "Government IDs & Schemes",
            {
                "fields": ("aadhar_no", "hrms_id", "swasthya_sathi"),
            },
        ),
        (
            "Education & Skills",
            {
                "fields": ("qualification", "computer_knowledge"),
            },
        ),
        (
            "Bank Details",
            {
                "fields": ("bank_details",),
                "classes": ("collapse",),  # collapsed by default (less clutter)
            },
        ),
        (
            "CD Registration & Training",
            {
                "fields": (
                    "registration_date",
                    "basic_training_details",
                    "special_training_details",
                    "extra_activities",
                    "exceptional_performance",
                    "documents_ref",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY ADMIN
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(OfficeDutyPeriod)
class OfficeDutyPeriodAdmin(admin.ModelAdmin):
    """Browse and correct office-duty periods (staff use)."""

    list_display = ("volunteer", "started_at", "ended_at", "recorded_by", "created_at")
    list_filter = ("volunteer__unit",)
    search_fields = ("volunteer__name", "notes")
    autocomplete_fields = ("volunteer", "recorded_by")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "started_at"


@admin.register(VolunteerOfficeDutyMonth)
class VolunteerOfficeDutyMonthAdmin(admin.ModelAdmin):
    list_display = (
        "volunteer",
        "year",
        "month",
        "days_worked",
        "recorded_by",
        "updated_at",
    )
    list_filter = ("year", "month", "volunteer__unit")
    search_fields = ("volunteer__name", "volunteer__serial_no")
    autocomplete_fields = ("volunteer", "recorded_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OfficeDutyMonthSubmission)
class OfficeDutyMonthSubmissionAdmin(admin.ModelAdmin):
    list_display = ("unit", "year", "month", "submitted_by", "updated_at")
    list_filter = ("year", "month")
    search_fields = ("unit__name",)
    autocomplete_fields = ("unit", "submitted_by")
    readonly_fields = ("created_at", "updated_at")
