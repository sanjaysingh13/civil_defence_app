"""Equipment app — Django Admin configuration."""

from django import forms
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from civil_defence_app.personnel.models import Unit

from .asset_tag import build_next_unique_id
from .models import Equipment
from .models import EquipmentMaintenanceLog
from .models import EquipmentType

# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT ADMIN FORM
#
# The Equipment model still allows equipment_type=NULL for legacy rows created
# before types existed.  For *new* rows we require a type in Admin so inventory
# stays normalised; the form also mirrors seed_equipment-style asset tags.
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentAdminForm(forms.ModelForm):
    """
    ModelForm used only by ``EquipmentAdmin``.

    Behaviour on **add**:
      * ``equipment_type`` is required so staff pick a master type (or use the
        green “+” to create one inline) instead of typing a duplicate free-text name.
      * ``unique_id`` is optional in the form; ``clean()`` assigns the next
        ``UNIT-CODE-NNN`` value when both unit and type are present, matching
        ``seed_equipment`` / ``asset_tag.build_next_unique_id``.
      * If ``name`` is left blank, it defaults to the type’s canonical name.

    On **change**, defaults are left untouched so existing records behave as before.
    """

    class Meta:
        model = Equipment
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_add = self.instance.pk is None
        if is_add:
            self.fields["unique_id"].required = False
            self.fields["equipment_type"].required = True
            self.fields["unique_id"].help_text = (
                "Filled automatically after you choose Unit and Equipment Type "
                "(you may edit before saving)."
            )

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk is not None:
            return cleaned_data

        unit = cleaned_data.get("unit")
        equipment_type = cleaned_data.get("equipment_type")
        if not unit or not equipment_type:
            return cleaned_data

        name_val = (cleaned_data.get("name") or "").strip()
        if not name_val:
            cleaned_data["name"] = equipment_type.name

        uid = (cleaned_data.get("unique_id") or "").strip()
        if not uid:
            cleaned_data["unique_id"] = build_next_unique_id(
                unit=unit,
                equipment_type=equipment_type,
            )

        return cleaned_data


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
    list_filter = ("category",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at", "instance_count")

    # fieldsets groups the edit form into logical sections.
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "category", "scheduled_maintenance_periodicity"),
            },
        ),
        (
            "Description",
            {
                "fields": ("description",),
                "classes": ("wide",),
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
    model = EquipmentMaintenanceLog
    extra = 0
    fields = ("check_date", "is_fit", "status_after_check", "checked_by", "remarks")
    readonly_fields = ("created_at",)


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT ADMIN
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    form = EquipmentAdminForm

    list_display = (
        "name",
        "equipment_type",
        "unique_id",
        "category",
        "unit",
        "is_functional",
        "status",
        "last_check_date",
        "next_due_date",
    )
    list_filter = ("category", "status", "is_functional", "unit", "equipment_type")
    search_fields = ("name", "unique_id")
    # Autocomplete only for Unit (many rows). EquipmentType uses a normal
    # <select> so all types are visible without typing — the old autocomplete
    # widget looked “empty” until you searched, which confused operators.
    autocomplete_fields = ("unit",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [MaintenanceLogInline]

    fieldsets = (
        (
            "Assignment & type",
            {
                "description": (
                    "Choose the district unit and equipment type first. "
                    "Use the “+” beside Equipment Type to add a new type if needed."
                ),
                "fields": ("unit", "equipment_type"),
            },
        ),
        (
            "Identification",
            {
                "fields": ("name", "unique_id", "category"),
            },
        ),
        (
            "Quantity & condition",
            {
                "fields": ("quantity", "status", "is_functional"),
            },
        ),
        (
            "Maintenance schedule",
            {
                "fields": ("last_check_date", "next_due_date"),
            },
        ),
        (
            "Notes",
            {
                "fields": ("notes",),
                "classes": ("collapse",),
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

    def get_urls(self):
        """
        Append a JSON endpoint used by the add-form script to preview the next
        asset tag before submit.
        """
        return [
            path(
                "next-asset-tag/",
                self.admin_site.admin_view(self.next_asset_tag_view),
                name="equipment_equipment_next_asset_tag",
            ),
        ] + super().get_urls()

    def next_asset_tag_view(self, request):
        """
        Staff-only GET handler: ``?unit=<pk>&equipment_type=<pk>`` → next unique_id.

        Returns JSON ``{ "unique_id": "...", "error": null }`` or an error
        payload with 4xx status if parameters are missing or invalid.
        """
        unit_id = request.GET.get("unit")
        type_id = request.GET.get("equipment_type")
        if not unit_id or not type_id:
            return JsonResponse(
                {"unique_id": "", "error": "Select both unit and equipment type."},
                status=400,
            )
        try:
            unit = Unit.objects.get(pk=unit_id)
            equipment_type = EquipmentType.objects.get(pk=type_id)
        except (Unit.DoesNotExist, EquipmentType.DoesNotExist):
            return JsonResponse(
                {"unique_id": "", "error": "Invalid unit or equipment type."},
                status=404,
            )
        uid = build_next_unique_id(unit=unit, equipment_type=equipment_type)
        return JsonResponse({"unique_id": uid, "error": None})


# ─────────────────────────────────────────────────────────────────────────────
# MAINTENANCE LOG ADMIN
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(EquipmentMaintenanceLog)
class EquipmentMaintenanceLogAdmin(admin.ModelAdmin):
    list_display = (
        "equipment",
        "check_date",
        "is_fit",
        "status_after_check",
        "checked_by",
    )
    list_filter = ("is_fit", "status_after_check", "equipment__unit")
    search_fields = ("equipment__name", "equipment__unique_id")
    autocomplete_fields = ("equipment",)
    readonly_fields = ("created_at", "updated_at")
