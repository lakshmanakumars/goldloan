import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def _gen_token():
    return secrets.token_urlsafe(32)


def _default_expiry():
    return timezone.now() + timedelta(hours=24)


class SignupRequest(models.Model):
    """Pending self-service signup request. Lives in the public schema
    (not a TenantAwareModel) because there is no tenant yet."""

    business_name = models.CharField(_('Business name'), max_length=200)
    slug = models.SlugField(_('Subdomain'), max_length=50)
    owner_username = models.CharField(_('Owner username'), max_length=150)
    owner_email = models.EmailField(_('Owner email'))
    owner_phone = models.CharField(_('Owner phone'), max_length=20)
    license_no = models.CharField(_('License #'), max_length=100, blank=True)
    gst_no = models.CharField(_('GST #'), max_length=20, blank=True)
    plan = models.CharField(_('Plan'), max_length=20, default='starter')

    token = models.CharField(_('Token'), max_length=64, unique=True,
                             default=_gen_token, db_index=True)
    expires_at = models.DateTimeField(_('Expires at'), default=_default_expiry)
    verified_at = models.DateTimeField(_('Verified at'), null=True, blank=True)
    tenant_created = models.ForeignKey('iam.Tenant', null=True, blank=True,
                                       on_delete=models.SET_NULL,
                                       related_name='signup_request')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Signup request')
        verbose_name_plural = _('Signup requests')

    def __str__(self):
        return f'{self.business_name} ({self.slug})'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_verified(self):
        return self.verified_at is not None
