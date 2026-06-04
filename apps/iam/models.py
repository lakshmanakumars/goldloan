from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class Tenant(models.Model):
    """A pawn broker who rents the SaaS. Lives in the public/shared schema."""

    class Status(models.TextChoices):
        TRIAL = 'trial', _('Trial')
        ACTIVE = 'active', _('Active')
        SUSPENDED = 'suspended', _('Suspended')

    class Plan(models.TextChoices):
        STARTER = 'starter', _('Starter')
        GROWTH = 'growth', _('Growth')
        PRO = 'pro', _('Pro')

    LANGUAGE_CHOICES = [
        ('en-in', _('English (India)')),
        ('te', _('Telugu')),
        ('hi', _('Hindi')),
    ]

    name = models.CharField(_('Business name'), max_length=200)
    slug = models.SlugField(
        _('Subdomain'),
        unique=True,
        db_index=True,
        help_text=_('Used as subdomain: <slug>.goldloan.in'),
    )
    default_language = models.CharField(
        _('Default language'),
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default='en-in',
        help_text=_('Default UI language for this broker\'s staff.'),
    )
    license_no = models.CharField(max_length=100, blank=True,
                                  help_text='Pawnbroker / NBFC license #')
    gst_no = models.CharField(max_length=20, blank=True)
    pan_no = models.CharField(max_length=10, blank=True)
    contact_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.TRIAL)
    plan = models.CharField(max_length=20, choices=Plan.choices,
                            default=Plan.STARTER)
    trial_ends_at = models.DateField(null=True, blank=True)

    # --- gold loan business config ---
    max_ltv_pct = models.DecimalField(
        _('Max LTV %'), max_digits=5, decimal_places=2,
        default=Decimal('75.00'),
        help_text=_('RBI cap is 75%. Apply on origination.'),
    )

    # --- white-label branding ---
    logo = models.ImageField(
        _('Logo'), upload_to='tenant/logos/', blank=True, null=True,
        help_text=_('Shown in the admin sidebar, emails and auction notices. '
                    'PNG/SVG with transparent background works best.'),
    )
    tagline = models.CharField(
        _('Tagline'), max_length=120, blank=True,
        help_text=_('Sub-heading under the business name, e.g. '
                    '"Gold Finance". Leave blank to hide.'),
    )
    primary_color = models.CharField(
        _('Primary colour'), max_length=7, default='#c46616',
        help_text=_('Brand colour as a hex code, e.g. #c46616. Themes the '
                    'admin UI, emails and auction notices.'),
    )
    accent_color = models.CharField(
        _('Accent colour'), max_length=7, default='#f59e0b',
        help_text=_('Secondary/highlight hex colour, e.g. #f59e0b.'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Pawn Broker (Tenant)'
        verbose_name_plural = 'Pawn Brokers (Tenants)'

    def __str__(self):
        return f'{self.name} ({self.slug})'

    @property
    def subdomain_url(self):
        from django.conf import settings
        return f'http://{self.slug}.{settings.TENANT_BASE_DOMAIN}:8000/'

    # --- branding helpers (used by email + PDF templates) ---
    @property
    def primary_dark(self):
        from apps.core import branding
        return branding.shade(self.primary_color or branding.DEFAULT_PRIMARY, -0.18)

    @property
    def primary_soft(self):
        """Very pale tint of the brand colour, for card/box backgrounds."""
        from apps.core import branding
        return branding.shade(self.primary_color or branding.DEFAULT_PRIMARY, 0.92)

    @property
    def monogram(self):
        """First letter of the business name, for the fallback logo badge."""
        return (self.name or '?').strip()[:1].upper()


class User(AbstractUser):
    """Custom user. is_superuser=True users are platform super-admins.

    Tenant users have tenant set; super-admins have tenant=None.
    """

    tenant = models.ForeignKey(
        Tenant,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='users',
        help_text=_('Null = platform super-admin.'),
        verbose_name=_('Tenant'),
    )
    phone = models.CharField(_('Phone'), max_length=20, blank=True)
    is_tenant_owner = models.BooleanField(
        _('Is tenant owner'),
        default=False,
        help_text=_('Tenant owners can manage their tenant settings & users.'),
    )
    language = models.CharField(
        _('Preferred UI language'),
        max_length=10,
        choices=Tenant.LANGUAGE_CHOICES,
        blank=True,
        help_text=_('Overrides the tenant default. Blank = use tenant default.'),
    )

    class Role(models.TextChoices):
        OWNER = 'owner', _('Owner')
        MANAGER = 'manager', _('Branch Manager')
        CASHIER = 'cashier', _('Cashier')
        APPRAISER = 'appraiser', _('Appraiser')
        AUDITOR = 'auditor', _('Auditor (read-only)')

    role = models.CharField(
        _('Role'), max_length=20, choices=Role.choices,
        default=Role.OWNER, blank=True,
        help_text=_('Determines what this user can do inside the tenant.'),
    )
    branch = models.ForeignKey(
        'iam.Branch', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='staff',
        help_text=_('Primary branch (used as default in forms).'),
    )

    class Meta:
        ordering = ['username']

    def __str__(self):
        if self.tenant:
            return f'{self.username} @ {self.tenant.slug}'
        return f'{self.username} (super-admin)'


class Branch(models.Model):
    """A physical office of a pawn broker. A tenant can have multiple."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(_('Branch name'), max_length=200)
    code = models.CharField(_('Code'), max_length=20,
                            help_text=_('Short code shown on receipts, e.g. HYD1'))
    address = models.TextField(_('Address'), blank=True)
    phone = models.CharField(_('Phone'), max_length=20, blank=True)
    license_no = models.CharField(_('License #'), max_length=100, blank=True,
                                  help_text=_('Overrides tenant license if set.'))
    gst_no = models.CharField(_('GST #'), max_length=20, blank=True,
                              help_text=_('Overrides tenant GST if set.'))
    is_active = models.BooleanField(_('Active'), default=True)
    is_primary = models.BooleanField(
        _('Primary branch'), default=False,
        help_text=_('Used as the default when no branch is selected.'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Branch')
        verbose_name_plural = _('Branches')
        ordering = ['tenant_id', '-is_primary', 'name']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'],
                                    name='uniq_branch_code_per_tenant'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'

    @classmethod
    def default_for(cls, tenant):
        """Return tenant's primary branch (or first active, or None)."""
        if tenant is None:
            return None
        b = cls.objects.filter(tenant=tenant, is_active=True,
                               is_primary=True).first()
        if b:
            return b
        return cls.objects.filter(tenant=tenant, is_active=True).first()
