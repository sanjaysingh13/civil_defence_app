"""Equipment app — Django Admin configuration."""

from django.contrib import admin

from .models import Equipment
from .models import EquipmentMaintenanceLog
from .models import EquipmentType
from .models import IncidentEquipment


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT TYPE ADMIN
#
# EquipmentType is a master-data table — there are only ~62 rows (one per
# equipment type from the procurement register).  The Admin lets the national
# office update descriptions and periodicity without a code change.
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    # list_display controls which columns appear in the changelist table.
    list_display = (
        "name",
        "category",
        "scheduled_maintenance_periodicity",
        "instance_count",
    )
    # list_filter adds sidebar filters so the Admin can browse by category.
    list_filter    = ("category",)
    search_fields  = ("name", "description")
    readonly_fields = ("created_at", "updated_at", "instance_count")

    # fieldsets groups the edit form into logical sections.
    fieldsets = (
        (None, {
            "fields": ("name", "category", "scheduled_maintenance_periodicity"),
        }),
        ("Description", {
            "fields": ("description",),
            "classes": ("wide",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="# Physical Units")
    def instance_count(self, obj):
        """
        Count of Equipment rows that belong to this EquipmentType.
        Django admin display methods decorated with @admin.display let us add
        computed columns to the changelist without a DB column.
        """
        return obj.equipment_instances.count()


# ─────────────────────────────────────────────────────────────────────────────
# MAINTENANCE LOG INLINE (used inside EquipmentAdmin)
# ─────────────────────────────────────────────────────────────────────────────

class MaintenanceLogInline(admin.TabularInline):
    model  = EquipmentMaintenanceLog
    extra  = 0
    fields = ("check_date", "is_fit", "status_after_check", "checked_by", "remarks")
    readonly_fields = ("created_at",)


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT ADMIN
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display   = (
        "name", "equipment_type", "unique_id", "category", "unit",
        "is_functional", "status", "last_check_date", "next_due_date",
    )
    list_filter    = ("category", "status", "is_functional", "unit", "equipment_type")
    search_fields  = ("name", "unique_id")
    # autocomplete_fields requires the target ModelAdmin to have search_fields set.
    # EquipmentTypeAdmin.search_fields = ("name", "description") — set above.
    autocomplete_fields = ("unit", "equipment_type")
    readonly_fields = ("created_at", "updated_at")
    inlines        = [MaintenanceLogInline]


# ─────────────────────────────────────────────────────────────────────────────
# MAINTENANCE LOG ADMIN
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(EquipmentMaintenanceLog)
class EquipmentMaintenanceLogAdmin(admin.ModelAdmin):
    list_display   = ("equipment", "check_date", "is_fit", "status_after_check", "checked_by")
    list_filter    = ("is_fit", "status_after_check", "equipment__unit")
    search_fields  = ("equipment__name", "equipment__unique_id")
    autocomplete_fields = ("equipment",)
    readonly_fields = ("created_at", "updated_at")
