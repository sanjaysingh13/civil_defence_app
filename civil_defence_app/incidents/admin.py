"""Incidents app — Django Admin configuration."""

from django.contrib import admin

from .models import Incident
from .models import IncidentAssignment
from .models import IncidentLog
from .models import IncidentMedia


class IncidentLogInline(admin.TabularInline):
    model  = IncidentLog
    extra  = 0
    fields = ("timestamp", "action_taken", "entered_by")
    readonly_fields = ("created_at",)


class IncidentAssignmentInline(admin.TabularInline):
    model  = IncidentAssignment
    extra  = 0
    fields = ("volunteer", "role", "notes")
    autocomplete_fields = ("volunteer",)


class IncidentMediaInline(admin.TabularInline):
    model  = IncidentMedia
    extra  = 0
    fields = ("file", "caption", "tags")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display   = ("incident_number", "title", "incident_type", "status", "unit", "start_time", "created_at")
    list_filter    = ("incident_type", "status", "unit")
    search_fields  = ("incident_number", "title", "location_text", "description")
    autocomplete_fields = ("unit",)
    # incident_number is auto-generated; mark as read-only so the admin
    # never shows an editable text box for it on the change form.
    readonly_fields = ("incident_number", "created_at", "updated_at")
    inlines        = [IncidentLogInline, IncidentAssignmentInline, IncidentMediaInline]

    fieldsets = (
        ("Basic Info", {
            "fields": ("incident_number", "unit", "title", "incident_type", "status"),
        }),
        ("Location & Time", {
            "fields": ("location_text", "latitude", "longitude", "start_time", "end_time"),
        }),
        ("Details", {
            "fields": ("description", "final_report", "reported_by"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
