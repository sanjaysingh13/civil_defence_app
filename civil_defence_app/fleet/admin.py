"""Fleet app — Django Admin configuration."""

from django.contrib import admin

from .models import IncidentVehicle
from .models import Vehicle
from .models import VehicleMaintenanceLog


class VehicleMaintenanceInline(admin.TabularInline):
    model  = VehicleMaintenanceLog
    extra  = 0
    fields = ("service_date", "status_after_service", "odometer_km", "serviced_by", "remarks")
    readonly_fields = ("created_at",)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display   = ("registration_no", "vehicle_type", "unit", "status",
                      "capacity", "last_service_date", "next_service_due")
    list_filter    = ("vehicle_type", "status", "unit")
    search_fields  = ("registration_no", "notes")
    autocomplete_fields = ("unit",)
    readonly_fields = ("created_at", "updated_at")
    inlines        = [VehicleMaintenanceInline]


@admin.register(VehicleMaintenanceLog)
class VehicleMaintenanceLogAdmin(admin.ModelAdmin):
    list_display   = ("vehicle", "service_date", "status_after_service", "odometer_km")
    list_filter    = ("status_after_service", "vehicle__unit")
    search_fields  = ("vehicle__registration_no",)
    autocomplete_fields = ("vehicle",)
    readonly_fields = ("created_at", "updated_at")
