from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField

from apps.core.models import TenantAwareModel, TimeStampedModel


class CashTransaction(TenantAwareModel, TimeStampedModel):
    """Every cash movement in or out of the broker's shop.

    Auto-posted rows (DISBURSE_OUT, REPAYMENT_IN) link back to the source
    loan/repayment via FK and are read-only in admin. Manual rows
    (OPENING / CAPITAL_IN / DRAWAL_OUT / EXPENSE_OUT / BANK_*) are
    entered by staff.
    """

    class Kind(models.TextChoices):
        OPENING         = 'opening',         _('Opening balance')
        DISBURSE_OUT    = 'disburse_out',    _('Loan disbursement (out)')
        REPAYMENT_IN    = 'repayment_in',    _('Loan repayment (in)')
        CAPITAL_IN      = 'capital_in',      _('Capital injection (in)')
        DRAWAL_OUT      = 'drawal_out',      _('Owner drawal (out)')
        EXPENSE_OUT     = 'expense_out',     _('Expense (out)')
        BANK_DEPOSIT    = 'bank_deposit',    _('Bank deposit (out of cash)')
        BANK_WITHDRAWAL = 'bank_withdrawal', _('Bank withdrawal (into cash)')
        ADJUSTMENT      = 'adjustment',      _('Adjustment')

    IN_KINDS = {Kind.OPENING, Kind.REPAYMENT_IN, Kind.CAPITAL_IN,
                Kind.BANK_WITHDRAWAL}
    OUT_KINDS = {Kind.DISBURSE_OUT, Kind.DRAWAL_OUT, Kind.EXPENSE_OUT,
                 Kind.BANK_DEPOSIT}
    NEUTRAL_KINDS = {Kind.ADJUSTMENT}  # sign determined per-row note

    class Mode(models.TextChoices):
        CASH   = 'cash',   _('Cash')
        UPI    = 'upi',    _('UPI')
        BANK   = 'bank',   _('Bank Transfer')
        CHEQUE = 'cheque', _('Cheque')

    txn_date = models.DateField(_('Date'), default=timezone.localdate,
                                db_index=True)
    kind = models.CharField(_('Kind'), max_length=20, choices=Kind.choices,
                            db_index=True)
    amount = MoneyField(_('Amount'), max_digits=14, decimal_places=2,
                        default_currency='INR')
    branch = models.ForeignKey('iam.Branch', null=True, blank=True,
                               on_delete=models.SET_NULL,
                               related_name='cash_transactions')
    source_loan = models.ForeignKey('loans.Loan', null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name='cash_transactions')
    source_repayment = models.ForeignKey('loans.Repayment', null=True,
                                         blank=True,
                                         on_delete=models.SET_NULL,
                                         related_name='cash_transactions')
    mode = models.CharField(_('Mode'), max_length=10, choices=Mode.choices,
                            default=Mode.CASH)
    note = models.TextField(_('Note'), blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                   blank=True, on_delete=models.SET_NULL,
                                   related_name='+')

    class Meta:
        ordering = ['-txn_date', '-id']
        indexes = [
            models.Index(fields=['tenant', 'txn_date']),
            models.Index(fields=['tenant', 'branch', 'txn_date']),
        ]
        verbose_name = _('Cash transaction')
        verbose_name_plural = _('Cash transactions')

    def __str__(self):
        sign = '-' if self.kind in self.OUT_KINDS else '+'
        return f'{self.txn_date} {sign}₹{self.amount.amount} {self.get_kind_display()}'

    def save(self, *args, **kwargs):
        # Auto-default branch to tenant's primary
        if not self.branch_id:
            from apps.iam.models import Branch
            from apps.core.tenancy import get_current_tenant
            tenant = self.tenant_id and self.tenant or get_current_tenant()
            self.branch = Branch.default_for(tenant)
        super().save(*args, **kwargs)

    @property
    def is_auto(self):
        return bool(self.source_loan_id or self.source_repayment_id)

    @property
    def in_amount(self):
        if self.kind in self.IN_KINDS:
            return self.amount.amount
        return Decimal('0.00')

    @property
    def out_amount(self):
        if self.kind in self.OUT_KINDS:
            return self.amount.amount
        return Decimal('0.00')


class DayClose(TenantAwareModel, TimeStampedModel):
    """Day-end cash reconciliation per branch."""

    close_date = models.DateField(_('Close date'), default=timezone.localdate,
                                  db_index=True)
    branch = models.ForeignKey('iam.Branch', on_delete=models.PROTECT,
                               related_name='day_closes')
    opening_balance = MoneyField(_('Opening balance'),
                                 max_digits=14, decimal_places=2,
                                 default_currency='INR',
                                 default=Decimal('0'))
    computed_in = MoneyField(_('Computed in'),
                             max_digits=14, decimal_places=2,
                             default_currency='INR', default=Decimal('0'))
    computed_out = MoneyField(_('Computed out'),
                              max_digits=14, decimal_places=2,
                              default_currency='INR', default=Decimal('0'))
    closing_balance = MoneyField(_('Closing balance (system)'),
                                 max_digits=14, decimal_places=2,
                                 default_currency='INR', default=Decimal('0'))
    physical_count = MoneyField(_('Physical count'),
                                max_digits=14, decimal_places=2,
                                default_currency='INR', default=Decimal('0'))
    variance = MoneyField(_('Variance'),
                          max_digits=14, decimal_places=2,
                          default_currency='INR', default=Decimal('0'))
    denomination_json = models.JSONField(_('Denominations'), default=dict,
                                         blank=True)
    notes = models.TextField(_('Notes'), blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                  blank=True, on_delete=models.SET_NULL,
                                  related_name='+')

    class Meta:
        ordering = ['-close_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'branch', 'close_date'],
                name='uniq_dayclose_per_tenant_branch_date'),
        ]
        verbose_name = _('Day close')
        verbose_name_plural = _('Day closes')

    def __str__(self):
        return f'{self.close_date} {self.branch.code} → ₹{self.closing_balance.amount}'
