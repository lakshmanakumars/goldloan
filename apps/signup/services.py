"""Signup business logic — separate from views so tests / management
commands can finalize without HTTP."""
import logging
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.iam.models import Tenant
from apps.iam.services import onboard_tenant, OnboardError
from apps.notifications.services import send_email, render_email
from .models import SignupRequest

log = logging.getLogger(__name__)


def _gen_password(n=12):
    alpha = string.ascii_letters
    digits = string.digits
    symbols = '!@#$%&*'
    pool = alpha + digits + symbols
    # Guarantee one of each required category
    pw = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]
    pw += [secrets.choice(pool) for _ in range(n - len(pw))]
    secrets.SystemRandom().shuffle(pw)
    return ''.join(pw)


def send_verification_email(signup: SignupRequest):
    verify_url = (f'{settings.SITE_BASE_URL}/signup/verify/{signup.token}/')
    ctx = {
        'owner_name': signup.owner_username,
        'business_name': signup.business_name,
        'slug': signup.slug,
        'verify_url': verify_url,
        'site_base_url': settings.SITE_BASE_URL,
        'tenant_base_domain': settings.TENANT_BASE_DOMAIN,
    }
    text, html = render_email('emails/signup_verify', ctx)
    return send_email(
        signup.owner_email,
        f'Confirm your Vaarahi signup for {signup.business_name}',
        text, html)


@transaction.atomic
def finalize_signup(signup: SignupRequest):
    """Convert a verified SignupRequest into a real Tenant. Returns
    (tenant, owner, password). Idempotent: if already finalized, returns
    the existing tenant and a None password."""
    if signup.tenant_created_id:
        return signup.tenant_created, signup.tenant_created.users.filter(
            is_tenant_owner=True).first(), None

    password = _gen_password()
    try:
        tenant, branch, owner = onboard_tenant(
            name=signup.business_name,
            slug=signup.slug,
            owner_username=signup.owner_username,
            owner_email=signup.owner_email,
            owner_password=password,
            phone=signup.owner_phone,
            license_no=signup.license_no,
            gst_no=signup.gst_no,
            plan=signup.plan,
            status=Tenant.Status.TRIAL,
            trial_ends_at=timezone.localdate() + timedelta(days=14),
        )
    except OnboardError as exc:
        log.exception('Signup finalize failed for %s', signup.slug)
        raise

    signup.verified_at = timezone.now()
    signup.tenant_created = tenant
    signup.save(update_fields=['verified_at', 'tenant_created'])

    # Send welcome email with credentials
    login_url = f'http://{tenant.slug}.{settings.TENANT_BASE_DOMAIN}:8765/admin/'
    text, html = render_email('emails/welcome', {
        'owner_name': owner.username,
        'owner_username': owner.username,
        'owner_password': password,
        'tenant': tenant,
        'login_url': login_url,
        'site_base_url': settings.SITE_BASE_URL,
    })
    send_email(owner.email, f'Welcome to {tenant.name}', text, html)

    return tenant, owner, password
