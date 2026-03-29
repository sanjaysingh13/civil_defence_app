from allauth.account.forms import SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django import forms
from django.contrib.auth import forms as admin_forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from .models import User

# ─────────────────────────────────────────────────────────────────────────────
# SHARED SIGNUP / ADMIN TELEPHONE RULE
#
# Regex matches exactly ten digits (Indian-style local mobile without +91).
# We attach the same validator in forms so users get immediate feedback;
# User.telephone on the model uses TELEPHONE_VALIDATOR for DB-level checks.
# ─────────────────────────────────────────────────────────────────────────────

_SIGNUP_TELEPHONE_VALIDATORS = [
    RegexValidator(
        regex=r"^\d{10}$",
        message=_("Enter exactly 10 digits (no spaces or dashes)."),
    ),
]


class UserAdminChangeForm(admin_forms.UserChangeForm):
    class Meta(admin_forms.UserChangeForm.Meta):
        model = User


class UserAdminCreationForm(admin_forms.AdminUserCreationForm):
    """
    Form for User Creation in the Admin Area.
    To change user signup, see UserSignupForm and UserSocialSignupForm.
    """

    class Meta(admin_forms.UserCreationForm.Meta):
        model = User
        # Base UserCreationForm only saves username + passwords; extra columns
        # must be listed here so ModelForm binds them and save() writes them.
        fields = (
            "username",
            "first_name",
            "last_name",
            "rank",
            "telephone",
        )
        error_messages = {
            "username": {"unique": _("This username has already been taken.")},
        }


# ─────────────────────────────────────────────────────────────────────────────
# BASE FORM: EXTRA PROFILE FIELDS (MUST SUBCLASS django.forms.Form)
#
# Django’s DeclarativeFieldsMetaclass only merges `declared_fields` from bases
# that went through that metaclass. A plain “mixin” class with CharField
# attributes is ignored, so those fields never appeared on UserSignupForm.
# Inheriting from forms.Form fixes that; we subclass this before SignupForm /
# SocialSignupForm so first_name, last_name, rank, telephone land in base_fields.
#
# django-allauth calls signup(request, user) on the form after creating the user;
# this base implements that hook once for both local and social signup forms.
# ─────────────────────────────────────────────────────────────────────────────


class CivilDefenceSignupProfileBase(forms.Form):
    first_name = forms.CharField(
        label=_("First name"),
        max_length=150,
        required=True,
    )
    last_name = forms.CharField(
        label=_("Last name"),
        max_length=150,
        required=True,
    )
    rank = forms.CharField(
        label=_("Rank"),
        max_length=128,
        required=True,
    )
    telephone = forms.CharField(
        label=_("Telephone"),
        max_length=10,
        min_length=10,
        required=True,
        validators=_SIGNUP_TELEPHONE_VALIDATORS,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "pattern": r"\d{10}",
                "autocomplete": "tel-national",
            },
        ),
        help_text=_("Exactly 10 digits, no spaces or country code."),
    )

    field_order = (
        "email",
        "username",
        "first_name",
        "last_name",
        "rank",
        "telephone",
        "password1",
        "password2",
    )

    def signup(self, request, user):
        """
        Persist custom profile fields after the core user row is created.

        allauth invokes this from custom_signup(); `user` already has username
        and password (and email setup follows). We copy validated POST data,
        derive `name` for backwards compatibility with list/search that still
        use the single `name` column, then save only the columns we touched.
        """
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.rank = self.cleaned_data["rank"]
        user.telephone = self.cleaned_data["telephone"]
        full = f"{user.first_name} {user.last_name}".strip()
        if full:
            user.name = full
        user.save(
            update_fields=["first_name", "last_name", "rank", "telephone", "name"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL ACCOUNT SIGNUP
#
# ACCOUNT_FORMS["signup"] points here. CivilDefenceSignupProfileBase must be
# listed before SignupForm so its declared_fields merge into this class.
# ─────────────────────────────────────────────────────────────────────────────


class UserSignupForm(CivilDefenceSignupProfileBase, SignupForm):
    """
    Form that will be rendered on a user sign up section/screen.
    Default fields will be added automatically.
    Check UserSocialSignupForm for accounts created from social.
    """


# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL ACCOUNT SIGNUP
#
# SOCIALACCOUNT_FORMS["signup"] points here. Same profile base as local signup.
# ─────────────────────────────────────────────────────────────────────────────


class UserSocialSignupForm(CivilDefenceSignupProfileBase, SocialSignupForm):
    """
    Renders the form when user has signed up using social accounts.
    Default fields will be added automatically.
    See UserSignupForm otherwise.
    """
