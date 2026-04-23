"""
Equipment app views.

EquipmentListView                 — paginated, filterable table of all equipment items.
EquipmentCreateView               — Admin-only: add item with auto asset tag.
EquipmentDetailView               — full detail card for one item with maintenance history.
EquipmentMaintenanceLogCreateView — UIC submits a new inspection result for one item.
EquipmentInventorySummaryView     — all-units summary: total/functional/non-functional/overdue per unit.
EquipmentInventoryByUnitView      — per-unit type-breakdown (drill-down from summary).
EquipmentMaintenanceByUnitView    — all maintenance logs for a unit's equipment.
EquipmentOverdueView              — items with overdue or never-inspected maintenance.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView

from .asset_tag import build_next_unique_id
from .forms import EquipmentCreateForm
from .forms import EquipmentMaintenanceLogForm
from .models import Equipment
from .models import EquipmentCategory
from .models import EquipmentMaintenanceLog
from .models import EquipmentStatus
from .models import add_months

# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT LIST
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentListView(LoginRequiredMixin, ListView):
    """Table of all equipment across all units with filters."""

    model = Equipment
    template_name = "equipment/equipment_list.html"
    context_object_name = "equipment_list"
    paginate_by = 50

    def get_queryset(self):
        qs = Equipment.objects.select_related("unit", "equipment_type").order_by(
            "unit__name", "equipment_type__name", "unique_id"
        )

        self.q = self.request.GET.get("q", "").strip()
        self.category = self.request.GET.get("category", "").strip()
        self.status = self.request.GET.get("status", "").strip()
        self.unit_id = self.request.GET.get("unit", "").strip()
        # ?functional=1 → only functional items; ?functional=0 → only non-functional;
        # empty string (default) → no filter applied (show all).
        self.functional = self.request.GET.get("functional", "").strip()

        if self.q:
            qs = qs.filter(
                Q(equipment_type__name__icontains=self.q)
                | Q(unique_id__icontains=self.q)
                | Q(name__icontains=self.q)
            )
        if self.category:
            qs = qs.filter(category=self.category)
        if self.status:
            qs = qs.filter(status=self.status)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)
        if self.functional == "1":
            qs = qs.filter(is_functional=True)
        elif self.functional == "0":
            qs = qs.filter(is_functional=False)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.q
        context["selected_category"] = self.category
        context["selected_status"] = self.status
        context["selected_unit"] = self.unit_id
        context["selected_functional"] = self.functional
        context["category_choices"] = EquipmentCategory.choices
        context["status_choices"] = EquipmentStatus.choices
        from civil_defence_app.personnel.models import Unit

        context["units"] = Unit.objects.order_by("name")
        user = self.request.user
        context["can_add_equipment"] = user.is_superuser or getattr(
            user,
            "is_admin_role",
            False,
        )
        return context


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT CREATE (Admin web UI)
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    POST creates a new ``Equipment`` with ``unique_id`` from ``build_next_unique_id``,
    ``name``/``category`` copied from the chosen ``EquipmentType``, and
    ``is_functional=True``. Asset tag is shown on the redirect target (detail page).
    """

    model = Equipment
    form_class = EquipmentCreateForm
    template_name = "equipment/equipment_create.html"

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_superuser or getattr(user, "is_admin_role", False)

    def form_valid(self, form):
        with transaction.atomic():
            equipment = form.save(commit=False)
            et = equipment.equipment_type
            unit = equipment.unit
            equipment.name = et.name.strip()
            equipment.category = et.category
            equipment.unique_id = build_next_unique_id(unit=unit, equipment_type=et)
            equipment.is_functional = True
            equipment.status = EquipmentStatus.FUNCTIONAL
            equipment.save()
        messages.success(
            self.request,
            f"Equipment created. Asset tag: {equipment.unique_id}",
        )
        return redirect(
            reverse("equipment:equipment-detail", kwargs={"pk": equipment.pk}),
        )


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT DETAIL
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentDetailView(LoginRequiredMixin, DetailView):
    model = Equipment
    template_name = "equipment/equipment_detail.html"

    def get_queryset(self):
        # prefetch_related pulls all maintenance log rows in a single extra
        # SQL query so the template can iterate them without N+1 queries.
        return Equipment.objects.select_related(
            "unit", "equipment_type"
        ).prefetch_related(
            "maintenance_logs__checked_by",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass a flag so the template can show/hide the "Add Maintenance Log"
        # button based on the user's role and unit ownership.
        user = self.request.user
        is_admin = user.is_superuser or getattr(user, "is_admin_role", False)
        is_owning_uic = (
            getattr(user, "is_unit_in_charge", False) and user.unit == self.object.unit
        )
        context["can_log"] = user.is_authenticated and (is_admin or is_owning_uic)
        return context


# ─────────────────────────────────────────────────────────────────────────────
# MAINTENANCE LOG — CREATE
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentMaintenanceLogCreateView(
    LoginRequiredMixin, UserPassesTestMixin, CreateView
):
    """
    Unit In-Charge submits a new maintenance inspection result for one
    piece of equipment.

    URL: /equipment/<pk>/log/add/
    The equipment PK comes from the URL; the UIC is taken from request.user.

    Access rules (test_func):
      • Django superusers always pass.
      • Must have role=UNIT_IN_CHARGE AND have a unit assigned.
      • The equipment must belong to the UIC's unit — otherwise 403.

    On a valid POST:
      1. Creates the EquipmentMaintenanceLog row.
      2. Updates Equipment.is_functional from is_fit.
      3. Updates Equipment.last_check_date from check_date.
      4. Updates Equipment.status (OK if fit, REPAIR if not fit).
      5. If equipment_type is set, computes next_due_date = check_date +
         scheduled_maintenance_periodicity months using add_months().
      6. Redirects back to the equipment detail page with a success flash.
    """

    model = EquipmentMaintenanceLog
    form_class = EquipmentMaintenanceLogForm
    template_name = "equipment/log_create.html"

    def setup(self, request, *args, **kwargs):
        """
        setup() runs before dispatch() and before test_func().
        We resolve the Equipment object here once so both test_func and
        the form handlers can use self.equipment without repeating the query.
        """
        super().setup(request, *args, **kwargs)
        self.equipment = get_object_or_404(
            Equipment.objects.select_related("unit", "equipment_type"),
            pk=kwargs["pk"],
        )

    def test_func(self) -> bool:
        """
        UserPassesTestMixin calls this before rendering the view.
        Returns True for superusers, admins, and the owning UIC.
        """
        user = self.request.user
        if user.is_superuser or getattr(user, "is_admin_role", False):
            return True
        return (
            getattr(user, "is_unit_in_charge", False)
            and user.unit == self.equipment.unit
        )

    def get_context_data(self, **kwargs):
        """Pass the equipment to the template so we can display its name."""
        context = super().get_context_data(**kwargs)
        context["equipment"] = self.equipment
        return context

    def form_valid(self, form):
        """
        Called when the submitted form passes validation.

        form.save(commit=False) creates the model instance WITHOUT hitting the
        database yet, giving us a chance to fill in auto-managed fields
        (equipment FK and checked_by) before the final INSERT.
        """
        log = form.save(commit=False)
        log.equipment = self.equipment
        log.checked_by = self.request.user
        log.status_after_check = (
            EquipmentStatus.FUNCTIONAL if log.is_fit else EquipmentStatus.REPAIR
        )
        log.save()

        # ── Propagate fitness result back to the equipment item ───────────────
        self.equipment.is_functional = log.is_fit
        self.equipment.last_check_date = log.check_date
        self.equipment.status = log.status_after_check

        # ── Calculate next_due_date from the equipment type's periodicity ─────
        #
        # add_months() is defined in models.py and handles month-end clamping
        # safely (e.g. Jan 31 + 1 month → Feb 28, not a crash).
        # We only compute this if the equipment has a type assigned.
        update_fields = ["is_functional", "last_check_date", "status"]
        if self.equipment.equipment_type:
            periodicity = (
                self.equipment.equipment_type.scheduled_maintenance_periodicity
            )
            self.equipment.next_due_date = add_months(log.check_date, periodicity)
            update_fields.append("next_due_date")

        self.equipment.save(update_fields=update_fields)

        messages.success(
            self.request,
            f"Maintenance log recorded for {self.equipment.unique_id}. "
            f"Functional status updated to: "
            f"{'Fit' if log.is_fit else 'Not Fit'}.",
        )
        return redirect(
            reverse("equipment:equipment-detail", kwargs={"pk": self.equipment.pk})
        )


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT INVENTORY SUMMARY — ALL UNITS
#
# Purpose: "Inventory by unit — totals"
#
# Shows every unit in a single table with aggregate counts:
#   total items · functional · non-functional · overdue (or never inspected)
#
# Each row links to the per-unit type-breakdown (EquipmentInventoryByUnitView)
# for drill-down detail.  This gives the Admin a one-page health snapshot of
# the entire state's equipment without having to navigate unit by unit.
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentInventorySummaryView(LoginRequiredMixin, TemplateView):
    """
    All-units equipment inventory summary.

    URL: /equipment/inventory/
    Access: any authenticated user.
      • Admins  — see all units in the table.
      • UICs    — redirected straight to their own unit's detail page, because
                  a single-row summary is not useful for a UIC.

    Single annotated queryset:
        Unit.objects.annotate(
            total, functional, non_functional, overdue
        )

    All four counts come from one SQL query (using conditional COUNT with Q
    filters) rather than four separate queries per unit.  With 28 units this
    is fast enough without pagination.
    """

    template_name = "equipment/inventory_summary.html"

    def get(self, request, *args, **kwargs):
        user = request.user
        is_admin = user.is_superuser or getattr(user, "is_admin_role", False)

        # UICs don't need a summary of all units — redirect them straight to
        # their own unit's detail view so they land on useful information.
        if not is_admin and getattr(user, "is_unit_in_charge", False) and user.unit:
            from django.shortcuts import redirect as _redirect

            return _redirect("equipment:unit-inventory", unit_pk=user.unit.pk)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = datetime.date.today()

        # ── Single annotated queryset: one row per unit, four counts ──────────
        #
        # Django's Count with a filter= kwarg translates to:
        #   COUNT(CASE WHEN <condition> THEN equipment.id END)
        # so all four aggregates run in a single GROUP BY query.
        #
        # The overdue condition matches EquipmentOverdueView exactly:
        #   (next_due_date < today OR last_check_date IS NULL) AND is_functional=True

        from civil_defence_app.personnel.models import Unit

        overdue_condition = Q(equipment_items__is_functional=True) & (
            Q(equipment_items__next_due_date__lt=today)
            | Q(equipment_items__last_check_date__isnull=True)
        )

        units = (
            Unit.objects.annotate(
                total=Count("equipment_items"),
                functional=Count(
                    "equipment_items", filter=Q(equipment_items__is_functional=True)
                ),
                non_functional=Count(
                    "equipment_items", filter=Q(equipment_items__is_functional=False)
                ),
                overdue=Count("equipment_items", filter=overdue_condition),
            )
            .filter(total__gt=0)  # hide units that have no equipment at all
            .order_by("name")
        )

        context["units"] = units
        context["today"] = today
        # Grand totals for the footer summary row.
        context["grand_total"] = sum(u.total for u in units)
        context["grand_functional"] = sum(u.functional for u in units)
        context["grand_nonfunctional"] = sum(u.non_functional for u in units)
        context["grand_overdue"] = sum(u.overdue for u in units)

        return context


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT INVENTORY BY UNIT  (per-unit type breakdown — drill-down)
#
# Purpose: "See inventory unit-wise — by type"
#
# Shows all equipment for a given unit, grouped by EquipmentType (or by name
# for untyped items).  For each type, displays total count, functional count,
# and non-functional count so the UIC can see stock levels at a glance.
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentInventoryByUnitView(LoginRequiredMixin, TemplateView):
    """
    Unit-wise inventory view, grouping equipment by EquipmentType.

    URL: /equipment/unit/<unit_pk>/inventory/
    Access: any authenticated user (admins see any unit; UICs see their own unit
            plus any unit if they navigate directly — we don't restrict viewing).
    """

    template_name = "equipment/unit_inventory.html"

    def get(self, request, *args, **kwargs):
        # Resolve the Unit object or return 404 if the PK doesn't exist.
        # We import here to avoid circular imports at module level.
        from civil_defence_app.personnel.models import Unit

        self.unit = get_object_or_404(Unit, pk=kwargs["unit_pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unit"] = self.unit

        # ── Typed inventory: grouped by EquipmentType ────────────────────────
        #
        # We use Django's annotation capabilities to produce a GROUP BY query
        # that counts total, functional, and non-functional items per type.
        #
        # Q objects (from django.db.models) allow conditional aggregation:
        #   Count('id', filter=Q(is_functional=True)) → SQL COUNT(CASE WHEN …)
        #
        # The result is a list of dicts with keys:
        #   equipment_type, equipment_type__name, equipment_type__category,
        #   equipment_type__scheduled_maintenance_periodicity,
        #   total, functional, non_functional

        typed_inventory = (
            Equipment.objects.filter(unit=self.unit, equipment_type__isnull=False)
            .values(
                "equipment_type",
                "equipment_type__name",
                "equipment_type__category",
                "equipment_type__scheduled_maintenance_periodicity",
            )
            .annotate(
                total=Count("id"),
                functional=Count("id", filter=Q(is_functional=True)),
                non_functional=Count("id", filter=Q(is_functional=False)),
            )
            .order_by("equipment_type__name")
        )

        # ── Untyped inventory: grouped by name ───────────────────────────────
        #
        # Handles legacy equipment that hasn't been assigned a type yet.

        untyped_inventory = (
            Equipment.objects.filter(unit=self.unit, equipment_type__isnull=True)
            .values("name", "category")
            .annotate(
                total=Count("id"),
                functional=Count("id", filter=Q(is_functional=True)),
                non_functional=Count("id", filter=Q(is_functional=False)),
            )
            .order_by("name")
        )

        context["typed_inventory"] = list(typed_inventory)
        context["untyped_inventory"] = list(untyped_inventory)

        # Summary totals for the header card.
        context["total_items"] = Equipment.objects.filter(unit=self.unit).count()
        context["functional_items"] = Equipment.objects.filter(
            unit=self.unit, is_functional=True
        ).count()
        context["nonfunctional_items"] = Equipment.objects.filter(
            unit=self.unit, is_functional=False
        ).count()

        # For the Admin to see all units for navigation.
        from civil_defence_app.personnel.models import Unit

        context["all_units"] = Unit.objects.order_by("name")

        return context


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT MAINTENANCE BY UNIT
#
# Purpose: "See maintenance logs unit-wise"
#
# Shows all EquipmentMaintenanceLog entries for equipment belonging to a
# specific unit, paginated and ordered most-recent first.  The Admin can use
# this to monitor whether UICs are actually doing their inspections.
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentMaintenanceByUnitView(LoginRequiredMixin, ListView):
    """
    All maintenance log entries for equipment belonging to a specific unit.

    URL: /equipment/unit/<unit_pk>/logs/
    """

    model = EquipmentMaintenanceLog
    template_name = "equipment/unit_maintenance_logs.html"
    context_object_name = "logs"
    paginate_by = 50

    def get(self, request, *args, **kwargs):
        from civil_defence_app.personnel.models import Unit

        self.unit = get_object_or_404(Unit, pk=kwargs["unit_pk"])
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        """
        Filter logs to only those belonging to equipment in self.unit.
        select_related prefetches the equipment and checked_by user in one
        query to avoid N+1 performance issues in the template.
        """
        return (
            EquipmentMaintenanceLog.objects.filter(equipment__unit=self.unit)
            .select_related("equipment", "equipment__unit", "checked_by")
            .order_by("-check_date", "-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unit"] = self.unit
        from civil_defence_app.personnel.models import Unit

        context["all_units"] = Unit.objects.order_by("name")
        return context


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT OVERDUE VIEW
#
# Purpose: "Flag delayed maintenance check"
#
# Shows all functional equipment items where maintenance is overdue.
# An item is overdue when:
#   A. next_due_date is set AND next_due_date < today  (scheduled overdue)
#   B. next_due_date is None AND last_check_date is None  (never inspected)
#
# For UICs: scoped to their unit only.
# For Admins: all units; can filter by unit via ?unit=<pk>.
# ─────────────────────────────────────────────────────────────────────────────


class EquipmentOverdueView(LoginRequiredMixin, ListView):
    """
    List of functional equipment items with overdue or missing maintenance.

    URL: /equipment/overdue/
    """

    model = Equipment
    template_name = "equipment/overdue.html"
    context_object_name = "overdue_items"
    paginate_by = 50

    def get_queryset(self):
        today = datetime.date.today()
        user = self.request.user

        # An item is considered overdue if it is functional AND either:
        #   • next_due_date is explicitly set and is in the past (condition A)
        #   • last_check_date is None meaning it has never been inspected (condition B)
        #
        # Q objects are combined with | (OR) to match either condition.
        # Non-functional and disposed items are excluded because they are already
        # flagged through the non-functional filter; only items expected to be
        # in-service need their maintenance checked.

        overdue_filter = Q(next_due_date__lt=today) | Q(last_check_date__isnull=True)

        qs = (
            Equipment.objects.filter(overdue_filter, is_functional=True)
            .select_related("unit", "equipment_type")
            .order_by("unit__name", "next_due_date", "equipment_type__name", "unique_id")
        )

        # UICs see only their own unit; Admins can filter optionally.
        is_admin = user.is_superuser or getattr(user, "is_admin_role", False)
        if not is_admin:
            # Non-admin users (UICs) are always scoped to their assigned unit.
            if user.unit:
                qs = qs.filter(unit=user.unit)
            else:
                qs = qs.none()
        else:
            # Admins can narrow down by unit via a GET parameter.
            self.unit_filter = self.request.GET.get("unit", "").strip()
            if self.unit_filter:
                qs = qs.filter(unit_id=self.unit_filter)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["today"] = datetime.date.today()
        context["total_overdue"] = self.get_queryset().count()

        user = self.request.user
        is_admin = user.is_superuser or getattr(user, "is_admin_role", False)
        context["is_admin"] = is_admin

        if is_admin:
            from civil_defence_app.personnel.models import Unit

            context["all_units"] = Unit.objects.order_by("name")
            context["selected_unit"] = getattr(self, "unit_filter", "")
        else:
            context["unit"] = user.unit

        return context
