"""
Equipment app URL configuration.
Mounted under "equipment/" prefix with namespace "equipment".

URL map:
  /equipment/                            → EquipmentListView (all equipment, filterable)
  /equipment/<pk>/                       → EquipmentDetailView (single item + maintenance history)
  /equipment/<pk>/log/add/               → EquipmentMaintenanceLogCreateView (UIC-only)
  /equipment/unit/<unit_pk>/inventory/   → EquipmentInventoryByUnitView (unit-wise grouped inventory)
  /equipment/unit/<unit_pk>/logs/        → EquipmentMaintenanceByUnitView (unit-wise maintenance logs)
  /equipment/overdue/                    → EquipmentOverdueView (delayed/never-inspected items)
"""

from django.urls import path

from . import views

app_name = "equipment"

urlpatterns = [
    # ── Core equipment views ──────────────────────────────────────────────────

    # GET  /equipment/               → list all equipment items (filterable, paginated)
    path("", views.EquipmentListView.as_view(), name="equipment-list"),

    # GET  /equipment/<pk>/          → detail with maintenance history
    path("<int:pk>/", views.EquipmentDetailView.as_view(), name="equipment-detail"),

    # GET  /equipment/<pk>/log/add/  → maintenance log form (UIC/Admin only)
    # POST /equipment/<pk>/log/add/  → save log + update equipment functional status + next_due_date
    path("<int:pk>/log/add/", views.EquipmentMaintenanceLogCreateView.as_view(), name="equipment-log-add"),

    # ── Inventory summary (all units) ────────────────────────────────────────

    # GET  /equipment/inventory/
    #      → all-units summary table: total/functional/non-functional/overdue per unit
    #      → UICs are redirected straight to their own unit's detail
    path("inventory/", views.EquipmentInventorySummaryView.as_view(), name="equipment-inventory-summary"),

    # ── Unit-scoped views ─────────────────────────────────────────────────────

    # GET  /equipment/unit/<unit_pk>/inventory/
    #      → per-unit type breakdown (drill-down from summary)
    path("unit/<int:unit_pk>/inventory/", views.EquipmentInventoryByUnitView.as_view(), name="unit-inventory"),

    # GET  /equipment/unit/<unit_pk>/logs/
    #      → all maintenance log entries for one unit's equipment
    path("unit/<int:unit_pk>/logs/", views.EquipmentMaintenanceByUnitView.as_view(), name="unit-logs"),

    # ── Overdue flagging view ─────────────────────────────────────────────────

    # GET  /equipment/overdue/
    #      → list of functional items with overdue or never-completed maintenance
    path("overdue/", views.EquipmentOverdueView.as_view(), name="equipment-overdue"),
]
