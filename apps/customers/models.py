from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.core.models import TenantAwareModel, TimeStampedModel


class Customer(TenantAwareModel, TimeStampedModel):
    class Gender(models.TextChoices):
        MALE = 'M', _('Male')
        FEMALE = 'F', _('Female')
        OTHER = 'O', _('Other')

    code = models.CharField(max_length=30, db_index=True,
                            help_text='Auto-generated customer code')
    name = models.CharField(max_length=200)
    dob = models.DateField(null=True, blank=True, verbose_name='Date of birth')
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    phone = models.CharField(max_length=20, db_index=True)
    alt_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    pan = models.CharField(max_length=10, blank=True,
                           help_text='PAN number (uppercase)')
    aadhaar = models.CharField(
        max_length=12, blank=True,
        validators=[RegexValidator(r'^\d{12}$',
                                   'Aadhaar must be exactly 12 digits.')],
        help_text='12-digit Aadhaar number')

    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)

    branch = models.ForeignKey(
        'iam.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='customers',
        help_text=_('Home branch for this customer.'),
    )

    photo = models.ImageField(upload_to='customers/photos/', null=True,
                              blank=True)
    id_proof = models.FileField(upload_to='customers/id_proofs/', null=True,
                                blank=True, help_text='PAN / Aadhaar scan')
    notes = models.TextField(_('Notes'), blank=True)

    preferred_language = models.CharField(
        _('Preferred language'),
        max_length=10,
        choices=[
            ('en-in', _('English (India)')),
            ('te', _('Telugu')),
            ('hi', _('Hindi')),
        ],
        default='en-in',
        help_text=_('Used for SMS / WhatsApp reminders sent to this customer.'),
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'],
                                    name='uniq_customer_code_per_tenant'),
            models.UniqueConstraint(fields=['tenant', 'phone'],
                                    name='uniq_customer_phone_per_tenant'),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._next_code()
        if self.pan:
            self.pan = self.pan.upper().strip()
        if self.aadhaar:
            self.aadhaar = ''.join(c for c in self.aadhaar if c.isdigit())
        super().save(*args, **kwargs)

    @property
    def aadhaar_masked(self):
        """Aadhaar shown as XXXX-XXXX-1234 (only last 4 visible)."""
        if not self.aadhaar:
            return ''
        return f'XXXX-XXXX-{self.aadhaar[-4:]}'

    def whatsapp_link(self, message=''):
        """Return a wa.me click-to-send URL for this customer.

        Strips non-digits, prepends Indian country code 91 if 10 digits."""
        from urllib.parse import quote
        digits = ''.join(c for c in (self.phone or '') if c.isdigit())
        if len(digits) == 10:
            digits = '91' + digits
        if not digits:
            return ''
        if message:
            return f'https://wa.me/{digits}?text={quote(message)}'
        return f'https://wa.me/{digits}'

    def _next_code(self):
        from apps.core.tenancy import get_current_tenant
        tenant = self.tenant_id and self.tenant or get_current_tenant()
        if tenant is None:
            return 'C-TEMP'
        last = Customer.all_objects.filter(tenant=tenant).order_by('-id').first()
        next_n = (last.id + 1) if last else 1
        return f'C-{next_n:05d}'
