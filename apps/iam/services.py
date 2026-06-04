"""IAM service layer — extracted so both the `onboard_tenant` management
command and the self-service signup flow can reuse the same atomic
tenant + branch + owner creation logic."""
from django.db import transaction
from django.utils.text import slugify

from .models import Tenant, Branch, User


class OnboardError(Exception):
    """Raised when onboarding can't proceed (slug taken, username taken, etc.)."""


@transaction.atomic
def onboard_tenant(*, name, slug, owner_username, owner_email,
                   owner_password, phone, license_no='', gst_no='',
                   plan='starter', status=None, trial_ends_at=None):
    """Atomically create Tenant + primary Branch + owner User.

    Returns (tenant, branch, owner). Raises OnboardError on conflict.
    """
    slug = (slug or slugify(name)).lower()

    if Tenant.objects.filter(slug=slug).exists():
        raise OnboardError(f"Tenant slug '{slug}' already exists.")
    if User.objects.filter(username=owner_username).exists():
        raise OnboardError(f"Username '{owner_username}' already taken.")
    if owner_email and User.objects.filter(email=owner_email).exists():
        raise OnboardError(f"Email '{owner_email}' already used.")

    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        license_no=license_no,
        gst_no=gst_no,
        contact_name=owner_username,
        contact_email=owner_email,
        contact_phone=phone,
        plan=plan,
        status=status or Tenant.Status.ACTIVE,
        trial_ends_at=trial_ends_at,
    )

    branch = Branch.objects.create(
        tenant=tenant,
        name='Main Branch',
        code='MAIN',
        phone=phone,
        license_no=license_no,
        gst_no=gst_no,
        is_primary=True,
        is_active=True,
    )

    owner = User(
        username=owner_username,
        email=owner_email,
        phone=phone,
        tenant=tenant,
        is_tenant_owner=True,
        is_staff=True,
        is_active=True,
        role=User.Role.OWNER,
        branch=branch,
    )
    owner.set_password(owner_password)
    owner.save()

    return tenant, branch, owner
