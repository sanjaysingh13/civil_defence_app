"""Equipment app — Django Admin configuration."""

from django.contrib import admin

from .models import Equipment
from .models import EquipmentMaintenanceLog
from .models import IncidentEquipment


class MaintenanceLogInline(admin.TabularInline):
    model  = EquipmentMaintenanceLog
    extra  = 0
    fields = ("check_date", "status_after_check", "checked_by", "remarks")
    readonly_fields = ("created_at",)


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display   = ("name", "unique_id", "category", "unit", "quantity", "status",
                      "last_check_date", "next_due_date")
    list_filter    = ("category", "status", "unit")
    search_fields  = ("name", "unique_id")
    autocomplete_fields = ("unit",)
    readonly_fields = ("created_at", "updated_at")
    inlines        = [MaintenanceLogInline]


@admin.register(EquipmentMaintenanceLog)
class EquipmentMaintenanceLogAdmin(admin.ModelAdmin):
    list_display   = ("equipment", "check_date", "status_after_check", "checked_by")
    list_filter    = ("status_after_check", "equipment__unit")
    search_fields  = ("equipment__name", "equipment__unique_id")
    autocomplete_fields = ("equipment",)
    readonly_fields = ("created_at", "updated_at")
