from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import User

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    """
    Admin configuration for the custom User model.

    Extends Django's default UserAdmin to include the two new fields:
      - role  : shown in "Civil Defence Role" fieldset
      - unit  : the district unit this user manages

    list_display adds role + unit so the admin list page is useful for
    quickly seeing who is assigned where.
    autocomplete_fields uses the Unit admin's search_fields for a
    type-ahead lookup instead of a giant dropdown.
    """

    form = UserAdminChangeForm
    add_form = UserAdminCreationForm

    # ── Fieldsets control the layout of the change-user form ─────────────────
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            _("Personal info"),
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "name",
                    "email",
                    "rank",
                    "telephone",
                ),
            },
        ),
        (
            # New section: Civil Defence-specific fields
            _("Civil Defence Role & Unit"),
            {"fields": ("role", "unit")},
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    # ── Columns visible in the admin list view ────────────────────────────────
    list_display = [
        "username",
        "first_name",
        "last_name",
        "name",
        "rank",
        "telephone",
        "role",
        "unit",
        "is_superuser",
    ]
    list_filter = ["role", "unit", "is_superuser", "is_active"]
    search_fields = [
        "name",
        "first_name",
        "last_name",
        "username",
        "email",
        "rank",
        "telephone",
    ]

    # autocomplete_fields requires the related model's admin to define
    # search_fields — Unit admin already has this set.
    autocomplete_fields = ["unit"]

    # ── Add-user form: same profile fields as signup (password optional in admin)
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "rank",
                    "telephone",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
