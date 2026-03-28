"""
Personnel app views.

We use Django's generic class-based views (ListView, DetailView) instead of
writing the list/detail logic from scratch.  These base classes provide:
  - ListView  : fetches a queryset, paginates it, passes it to a template
  - DetailView: fetches a single object by pk, passes it to a template

LoginRequiredMixin redirects anonymous visitors to the login page before
allowing access to any view that inherits from it.

get_queryset() lets us customise which rows are returned (e.g. apply search
filters from GET parameters).

get_context_data() lets us pass extra variables to the template on top of
the default ones (the paginated list / single object).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models import Q
from django.views.generic import DetailView
from django.views.generic import ListView

from .models import Unit
from .models import Volunteer


# ─────────────────────────────────────────────────────────────────────────────
# UNIT VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class UnitListView(LoginRequiredMixin, ListView):
    """
    Displays all 23 Civil Defence units as a sortable table.
    Annotates each unit with its active volunteer count so we can show it
    in the table without an extra query per row.
    """
    model               = Unit
    template_name       = "personnel/unit_list.html"
    context_object_name = "units"

    def get_queryset(self):
        # annotate() adds a computed field (volunteer_count) to each object.
        # Count('volunteers') counts rows in the related Volunteer table for
        # each Unit.  filter(volunteers__is_active=True) restricts the count
        # to active volunteers only.
        return (
            Unit.objects
            .annotate(volunteer_count=Count("volunteers", filter=Q(volunteers__is_active=True)))
            .order_by("name")
        )


class UnitDetailView(LoginRequiredMixin, DetailView):
    """
    Detail page for a single Unit: shows metadata plus a paginated
    table of its volunteers.
    """
    model         = Unit
    template_name = "personnel/unit_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass the unit's active volunteers to the template.
        context["volunteers"] = (
            self.object.volunteers
            .filter(is_active=True)
            .order_by("serial_no")
        )
        return context


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class VolunteerListView(LoginRequiredMixin, ListView):
    """
    Paginated, searchable, filterable table of all volunteers.

    Supported GET parameters:
      ?q=<name>      — case-insensitive name search
      ?unit=<id>     — filter to a specific unit
      ?gender=<M|F>  — filter by gender
    """
    model               = Volunteer
    template_name       = "personnel/volunteer_list.html"
    context_object_name = "volunteers"
    paginate_by         = 50       # 50 rows per page keeps the page fast

    def get_queryset(self):
        qs = (
            Volunteer.objects
            .select_related("unit")   # joins Unit in a single SQL query
            .filter(is_active=True)
            .order_by("unit__name", "serial_no")
        )

        self.q       = self.request.GET.get("q", "").strip()
        self.unit_id = self.request.GET.get("unit", "").strip()
        self.gender  = self.request.GET.get("gender", "").strip()

        if self.q:
            qs = qs.filter(name__icontains=self.q)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)
        if self.gender:
            qs = qs.filter(gender=self.gender)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass filter state back so the template can pre-fill the form
        # and build correct pagination URLs that preserve the filters.
        context["q"]            = self.q
        context["selected_unit"]= self.unit_id
        context["selected_gender"] = self.gender
        context["units"]        = Unit.objects.order_by("name")
        context["total_count"]  = self.get_queryset().count()
        return context


class VolunteerDetailView(LoginRequiredMixin, DetailView):
    """Full detail card for a single Volunteer."""
    model         = Volunteer
    template_name = "personnel/volunteer_detail.html"

    def get_queryset(self):
        return (
            Volunteer.objects
            .select_related("unit")
            .prefetch_related(
                "training_attendances__training_instance__training",
            )
        )
