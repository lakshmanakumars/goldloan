from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField

from apps.core.models import TenantAwareModel, TimeStampedModel


class Auction(TenantAwareModel, TimeStampedModel):
    """One auction row per gold-loan that has crossed NPA + maturity rules.

    Workflow:
        ELIGIBLE → NOTICE1_SENT  → (14d) →
        NOTICE2_SENT → (14d) →
        SCHEDULED → SOLD → POSTED  (or CANCELLED if borrower settles)
    """

    class Status(models.TextChoices):
        ELIGIBLE      = 'eligible',      _('Eligible for auction')
        NOTICE1_SENT  = 'notice1_sent',  _('Notice 1 sent')
        NOTICE2_SENT  = 'notice2_sent',  _('Notice 2 sent (final)')
        SCHEDULED     = 'scheduled',     _('Scheduled')
        SOLD          = 'sold',          _('Sold (awaiting posting)')
        POSTED        = 'posted',        _('Posted (settled)')
        CANCELLED     = 'cancelled',     _('Cancelled (borrower settled)')

    loan = models.OneToOneField('loans.Loan', on_delete=models.PROTECT,
                                related_name='auction')
    status = models.CharField(_('Status'), max_length=20,
                              choices=Status.choices,
                              default=Status.ELIGIBLE, db_index=True)

    eligible_at = models.DateTimeField(_('Eligible at'),
                                       default=timezone.now)
    notice1_sent_at = models.DateTimeField(_('Notice 1 sent at'),
                                           null=True, blank=True)
    notice2_sent_at = models.DateTimeField(_('Notice 2 sent at'),
                                           null=True, blank=True)
    scheduled_at = models.DateTimeField(_('Auction scheduled for'),
                                        null=True, blank=True)
    location = models.CharField(_('Auction location'), max_length=200, blank=True)

    bidder_name = models.CharField(_('Winning bidder'), max_length=200,
                                   blank=True)
    bidder_phone = models.CharField(_('Bidder phone'), max_length=20, blank=True)
    bidder_id_proof = models.CharField(_('Bidder ID proof'), max_length=80,
                                       blank=True)

    sold_amount = MoneyField(_('Sold for'), max_digits=14, decimal_places=2,
                             default_currency='INR', null=True, blank=True)
    total_dues_at_sale = MoneyField(_('Total dues at sale'),
                                    max_digits=14, decimal_places=2,
                                    default_currency='INR',
                                    null=True, blank=True)
    surplus_amount = MoneyField(_('Surplus refundable'),
                                max_digits=14, decimal_places=2,
                                default_currency='INR', default=Decimal('0'))
    shortfall_amount = MoneyField(_('Shortfall'),
                                  max_digits=14, decimal_places=2,
                                  default_currency='INR', default=Decimal('0'))
    surplus_refunded_at = models.DateTimeField(_('Surplus refunded at'),
                                               null=True, blank=True)
    notes = models.TextField(_('Notes'), blank=True)

    class Meta:
        ordering = ['-eligible_at']
        verbose_name = _('Auction')
        verbose_name_plural = _('Auctions')

    def __str__(self):
        return f'Auction for {self.loan.loan_no} [{self.get_status_display()}]'

    # ---- helpers ----

    @property
    def is_open(self):
        return self.status not in (self.Status.POSTED, self.Status.CANCELLED)

    @property
    def can_send_notice_1(self):
        return self.status == self.Status.ELIGIBLE

    @property
    def can_send_notice_2(self):
        if self.status != self.Status.NOTICE1_SENT:
            return False
        if self.notice1_sent_at is None:
            return False
        return (timezone.now() - self.notice1_sent_at).days >= 14

    @property
    def can_schedule(self):
        if self.status != self.Status.NOTICE2_SENT:
            return False
        if self.notice2_sent_at is None:
            return False
        return (timezone.now() - self.notice2_sent_at).days >= 14

    @property
    def can_record_sale(self):
        return self.status == self.Status.SCHEDULED

    @property
    def can_post_settlement(self):
        return self.status == self.Status.SOLD


class AuctionNotice(TenantAwareModel, TimeStampedModel):
    """Log of each notice sent — kept for the RBI audit trail."""

    auction = models.ForeignKey(Auction, on_delete=models.CASCADE,
                                related_name='notices')
    notice_no = models.PositiveSmallIntegerField(_('Notice #'))
    sent_at = models.DateTimeField(_('Sent at'), default=timezone.now)
    channels = models.JSONField(_('Channels'), default=list, blank=True,
                                help_text=_(
                                    'List of channels used, e.g. '
                                    '["email","whatsapp","registered_post"]'))
    delivery_ref = models.CharField(_('Delivery reference'), max_length=200,
                                    blank=True,
                                    help_text=_(
                                        'Email message id / Reg.Post tracking / etc.'))
    pdf_path = models.FileField(_('PDF copy'),
                                upload_to='auctions/notices/',
                                null=True, blank=True)
    sent_by = models.ForeignKey('iam.User', null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['-sent_at']
        constraints = [
            models.UniqueConstraint(
                fields=['auction', 'notice_no'],
                name='uniq_notice_per_auction'),
        ]
        verbose_name = _('Auction notice')
        verbose_name_plural = _('Auction notices')

    def __str__(self):
        return f'{self.auction.loan.loan_no} notice #{self.notice_no}'
