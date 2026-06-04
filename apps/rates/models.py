from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField

from apps.core.models import TenantAwareModel, TimeStampedModel


class GoldRate(TenantAwareModel, TimeStampedModel):
    """One row per (tenant, date, purity). Latest entry wins per date.

    Brokers usually enter the day's 22-carat rate every morning; you can
    optionally enter 24/18 for other purities.
    """

    class Source(models.TextChoices):
        MANUAL = 'manual', _('Manual entry')
        IBJA = 'ibja', _('IBJA feed')
        OTHER = 'other', _('Other')

    rate_date = models.DateField(_('Date'), default=timezone.now)
    purity_carat = models.DecimalField(
        _('Purity (carat)'), max_digits=4, decimal_places=2,
        default=Decimal('22.00'),
        help_text=_('Most pawn loans value at 22 ct.'),
    )
    rate_per_gram = MoneyField(
        _('Rate per gram'),
        max_digits=10, decimal_places=2, default_currency='INR',
    )
    source = models.CharField(_('Source'), max_length=10,
                              choices=Source.choices, default=Source.MANUAL)
    note = models.CharField(_('Note'), max_length=200, blank=True)

    class Meta:
        ordering = ['-rate_date', '-purity_carat']
        verbose_name = _('Gold rate')
        verbose_name_plural = _('Gold rates')
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'rate_date', 'purity_carat'],
                name='uniq_rate_per_tenant_date_purity'),
        ]

    def __str__(self):
        return f'{self.rate_date} {self.purity_carat}ct → ₹{self.rate_per_gram.amount}/g'

    @classmethod
    def latest_for(cls, tenant, purity_carat=Decimal('22.00'), on_date=None):
        # Use localdate (Asia/Kolkata) — UTC date can be one day behind IST.
        on_date = on_date or timezone.localdate()
        return (cls.all_objects
                .filter(tenant=tenant,
                        purity_carat=purity_carat,
                        rate_date__lte=on_date)
                .order_by('-rate_date').first())
