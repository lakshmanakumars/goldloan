from django.db import models
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField
from apps.core.models import TenantAwareModel, TimeStampedModel


class InterestReminder(TenantAwareModel, TimeStampedModel):
    class Channel(models.TextChoices):
        WHATSAPP = 'whatsapp', _('WhatsApp')
        SMS = 'sms', _('SMS')
        EMAIL = 'email', _('Email')
        LOG = 'log', _('Log only')

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SENT = 'sent', _('Sent')
        FAILED = 'failed', _('Failed')
        SKIPPED = 'skipped', _('Skipped')

    loan = models.ForeignKey('loans.Loan', on_delete=models.CASCADE,
                             related_name='reminders')
    period_month = models.DateField(
        help_text='First day of the month this reminder covers')
    interest_due = MoneyField(max_digits=12, decimal_places=2,
                              default_currency='INR')
    channel = models.CharField(max_length=10, choices=Channel.choices,
                               default=Channel.WHATSAPP)
    to_phone = models.CharField(max_length=20)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-period_month', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['loan', 'period_month', 'channel'],
                name='uniq_reminder_per_loan_month_channel'),
        ]

    def __str__(self):
        return f'{self.loan.loan_no} {self.period_month:%Y-%m} {self.channel}'
