from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField
from djmoney.money import Money

from apps.core.models import TenantAwareModel, TimeStampedModel

# How many times to regenerate an auto-number and retry the insert when it
# collides with another concurrent insert on its per-tenant unique constraint.
_MAX_NO_RETRIES = 5


class Loan(TenantAwareModel, TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        OVERDUE = 'overdue', _('Overdue')
        CLOSED = 'closed', _('Closed')
        AUCTIONED = 'auctioned', _('Auctioned')

    class RateType(models.TextChoices):
        ANNUAL = 'annual', _('Per Annum (% p.a.)')
        MONTHLY = 'monthly', _('Per Month (% p.m.)')

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='loans',
    )
    branch = models.ForeignKey(
        'iam.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='loans',
        help_text=_('Defaults to the tenant\'s primary branch if blank.'),
    )
    loan_no = models.CharField(max_length=30, db_index=True)
    principal = MoneyField(max_digits=12, decimal_places=2,
                           default_currency='INR')
    rate_type = models.CharField(
        max_length=10, choices=RateType.choices, default=RateType.ANNUAL,
        help_text='Is the rate below annual or monthly?',
    )
    interest_rate_pct = models.DecimalField(
        max_digits=6, decimal_places=3,
        help_text='Number only, e.g. 24.000. Combined with "Rate type" '
                  'on the left: 24 % p.a. or 2 % p.m.',
    )
    tenure_months = models.PositiveSmallIntegerField(
        default=12, help_text='Loan duration in calendar months (default 12).')
    start_date = models.DateField(default=timezone.now)
    maturity_date = models.DateField(
        blank=True,
        help_text='Auto-calculated as start_date + tenure_months.',
    )
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.ACTIVE)
    packet_no = models.CharField(max_length=50, blank=True,
                                 help_text='Physical packet / locker tag')
    purpose = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    renewed_to = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='renewed_from',
        help_text='If this loan was renewed/topped-up, points to the new loan.',
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'loan_no'],
                                    name='uniq_loan_no_per_tenant'),
        ]

    def __str__(self):
        return f'{self.loan_no} — {self.customer.name}'

    def save(self, *args, **kwargs):
        autogen_no = not self.loan_no
        if autogen_no:
            self.loan_no = self._next_no()
        if self.start_date and self.tenure_months and not self.maturity_date:
            self.maturity_date = self.start_date + relativedelta(
                months=int(self.tenure_months))
        if not self.branch_id:
            from apps.iam.models import Branch
            from apps.core.tenancy import get_current_tenant
            tenant = self.tenant_id and self.tenant or get_current_tenant()
            self.branch = Branch.default_for(tenant)
        if not autogen_no:
            super().save(*args, **kwargs)
            return
        # An auto-generated loan_no is computed before insert, so concurrent
        # inserts can pick the same number; the uniq_loan_no_per_tenant
        # constraint then rejects one. Regenerate and retry on collision.
        for attempt in range(_MAX_NO_RETRIES):
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                if attempt == _MAX_NO_RETRIES - 1:
                    raise
                self.loan_no = self._next_no()

    def _next_no(self):
        """Generate a year-scoped loan number: L-YYYY-NNNNN.

        NNNNN is a per-tenant running counter that resets to 1 at the start
        of each calendar year. The year is taken from the loan's start_date
        (the booking date), so the number follows the calendar year and the
        year prefix keeps numbers unique across years.
        """
        import datetime as _dt
        from apps.core.tenancy import get_current_tenant
        tenant = self.tenant_id and self.tenant or get_current_tenant()
        year = (self.start_date or timezone.localdate()).year
        prefix = f'L-{year}-'
        if tenant is None:
            return f'{prefix}00001'
        year_start = _dt.date(year, 1, 1)
        year_end = _dt.date(year + 1, 1, 1)
        count = Loan.all_objects.filter(
            tenant=tenant, start_date__gte=year_start,
            start_date__lt=year_end).count()
        return f'{prefix}{count + 1:05d}'

    @property
    def annual_rate_pct(self) -> Decimal:
        """Always return APR for disclosure on tickets / receipts."""
        if self.rate_type == self.RateType.MONTHLY:
            return (self.interest_rate_pct * Decimal('12')).quantize(
                Decimal('0.001'))
        return self.interest_rate_pct

    def whatsapp_reminder_link(self):
        """Click-to-send wa.me link with the reminder filled in.

        Uses the *current* interest due (accrued − paid) so the cashier
        sends the customer the real amount owed today, in their language.
        """
        from apps.notifications.tasks import _build_message
        msg = _build_message(self.tenant, self)  # auto-uses interest_due_now()
        return self.customer.whatsapp_link(msg)

    def monthly_interest(self) -> Money:
        if self.rate_type == self.RateType.MONTHLY:
            amt = self.principal.amount * self.interest_rate_pct / Decimal('100')
        else:  # ANNUAL
            amt = self.principal.amount * self.interest_rate_pct / Decimal('1200')
        return Money(amt.quantize(Decimal('0.01')), self.principal.currency)

    def total_paid_interest(self) -> Money:
        total = self.repayments.aggregate(
            s=models.Sum('interest_paid'))['s'] or Decimal('0')
        return Money(total, self.principal.currency)

    def total_waived_interest(self) -> Money:
        """Interest forgiven as a goodwill gesture (never cash received)."""
        total = self.repayments.aggregate(
            s=models.Sum('interest_waived'))['s'] or Decimal('0')
        return Money(total, self.principal.currency)

    def total_paid_principal(self) -> Money:
        total = self.repayments.aggregate(
            s=models.Sum('principal_paid'))['s'] or Decimal('0')
        return Money(total, self.principal.currency)

    def outstanding_principal(self) -> Money:
        return self.principal - self.total_paid_principal()

    # ---- duration-based interest ----

    def days_outstanding(self, on_date=None) -> int:
        on_date = on_date or timezone.localdate()
        return max((on_date - self.start_date).days, 0)

    def months_charged(self, on_date=None) -> int:
        """Number of monthly interest cycles owed.

        Pawn-broker convention: the first month's interest is charged
        upfront from day 0. After 30 days the second month kicks in,
        after 60 days the third, and so on. A loan whose start_date is
        still in the future hasn't begun → 0 months.
        """
        on_date = on_date or timezone.localdate()
        if self.start_date > on_date:
            return 0
        return (on_date - self.start_date).days // 30 + 1

    # Backward-compat alias for older callers.
    months_elapsed = months_charged

    def interest_accrued(self, on_date=None) -> Money:
        """Total interest that has built up from start_date to on_date.

        For the first 30 days a full month's interest is charged as a flat
        minimum. Beyond 30 days interest is pro-rated on actual days elapsed
        at a daily rate of monthly_interest / 30. (A loan whose start_date is
        still in the future hasn't begun → 0.)
        """
        days = self.days_outstanding(on_date)
        if self.start_date > (on_date or timezone.localdate()):
            return Money(Decimal('0.00'), self.principal.currency)
        monthly = self.monthly_interest().amount
        if days <= 30:
            amt = monthly
        else:
            amt = monthly * Decimal(days) / Decimal('30')
        amt = amt.quantize(Decimal('0.01'))
        return Money(amt, self.principal.currency)

    def interest_due_now(self, on_date=None) -> Money:
        """Accrued so far minus interest already paid AND interest waived.

        A waiver forgives accrued interest, so it reduces what's still owed
        just like a cash interest payment does — a paid+waived combination
        clears the interest in full.
        """
        due = (self.interest_accrued(on_date)
               - self.total_paid_interest()
               - self.total_waived_interest())
        if due.amount < 0:
            return Money(Decimal('0.00'), self.principal.currency)
        return due

    def ltv_breakdown(self, on_date=None):
        """Return apps.rates.ltv.compute() for this loan's items."""
        from apps.rates.ltv import compute
        return compute(self.tenant, list(self.items.all()), on_date=on_date)


class GoldItem(TenantAwareModel):
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE,
                             related_name='items')
    description = models.CharField(
        max_length=200, help_text=_('e.g. "2 gold bangles"'))
    gross_weight_g = models.DecimalField(
        _('Gross weight (g)'), max_digits=8, decimal_places=3,
        validators=[MinValueValidator(Decimal('0.000'))])
    stone_weight_g = models.DecimalField(
        _('Wastage (g)'), max_digits=8, decimal_places=3,
        default=Decimal('0.000'),
        validators=[MinValueValidator(Decimal('0.000'))])
    net_weight_g = models.DecimalField(
        _('Net weight (g)'), max_digits=8, decimal_places=3,
        null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.000'))],
        help_text=_('Leave blank to auto-compute as Gross − Wastage.'))
    purity_carat = models.DecimalField(
        _('Purity (ct)'), max_digits=4, decimal_places=2,
        default=Decimal('22.00'),
        validators=[MinValueValidator(Decimal('0.00'))])
    rate_per_gram = MoneyField(max_digits=10, decimal_places=2,
                               default_currency='INR',
                               null=True, blank=True)
    photo = models.ImageField(upload_to='loans/items/', null=True, blank=True)

    def __str__(self):
        return f'{self.description} ({self.net_weight_g}g {self.purity_carat}ct)'

    def clean(self):
        gross = Decimal(self.gross_weight_g or 0)
        stone = Decimal(self.stone_weight_g or 0)
        if gross < 0:
            raise ValidationError({'gross_weight_g':
                _('Gross weight cannot be negative.')})
        if stone < 0:
            raise ValidationError({'stone_weight_g':
                _('Stone weight cannot be negative.')})
        if stone > gross:
            raise ValidationError({'stone_weight_g':
                _('Stone weight (%(s)s g) cannot exceed gross weight '
                  '(%(g)s g).') % {'s': stone, 'g': gross}})
        if self.net_weight_g is not None and self.net_weight_g < 0:
            raise ValidationError({'net_weight_g':
                _('Net weight cannot be negative.')})
        # If net was provided but doesn't match gross-stone (allow small
        # appraiser rounding within 0.05g), reject the obvious mistakes.
        if self.net_weight_g is not None:
            expected = (gross - stone)
            if abs(Decimal(self.net_weight_g) - expected) > Decimal('0.05'):
                raise ValidationError({'net_weight_g':
                    _('Net weight (%(n)s g) does not match Gross − Stone '
                      '(%(e)s g). Leave blank to auto-compute.')
                    % {'n': self.net_weight_g, 'e': expected}})

    def save(self, *args, **kwargs):
        gross = Decimal(self.gross_weight_g or 0)
        stone = Decimal(self.stone_weight_g or 0)
        # Auto-fill net if blank, or fix if patently wrong (negative).
        if self.net_weight_g is None or Decimal(self.net_weight_g) < 0:
            self.net_weight_g = max(gross - stone, Decimal('0.000'))
        super().save(*args, **kwargs)


class Repayment(TenantAwareModel, TimeStampedModel):
    class Mode(models.TextChoices):
        CASH = 'cash', _('Cash')
        UPI = 'upi', _('UPI')
        BANK = 'bank', _('Bank Transfer')

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE,
                             related_name='repayments')
    paid_at = models.DateTimeField(default=timezone.now)
    principal_paid = MoneyField(max_digits=12, decimal_places=2,
                                default_currency='INR', default=Decimal('0'))
    interest_paid = MoneyField(max_digits=12, decimal_places=2,
                               default_currency='INR', default=Decimal('0'))
    interest_waived = MoneyField(
        max_digits=12, decimal_places=2, default_currency='INR',
        default=Decimal('0'),
        help_text='Interest forgiven as a goodwill gesture. NOT cash — it '
                  'reduces what the customer owes but is excluded from the '
                  'cash receipt total.')
    mode = models.CharField(max_length=10, choices=Mode.choices,
                            default=Mode.CASH)
    reference = models.CharField(max_length=100, blank=True,
                                 help_text='UPI ref / Bank txn id')
    receipt_no = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['-paid_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'receipt_no'],
                                    name='uniq_receipt_no_per_tenant'),
        ]

    def clean(self):
        """Guard against settling more than is actually owed.

        Balances are computed EXCLUDING this repayment (via its prior saved
        values when editing) so the check is correct for both add and edit.
        """
        super().clean()
        # Amounts can never be negative.
        neg = {}
        for fname in ('principal_paid', 'interest_paid', 'interest_waived'):
            if Decimal(getattr(self, fname).amount or 0) < 0:
                neg[fname] = _('Cannot be negative.')
        if neg:
            raise ValidationError(neg)
        if self.loan_id is None:
            return
        loan = self.loan
        tol = Decimal('0.01')
        cur = loan.principal.currency

        # Sum the OTHER repayments (everything on this loan except this row).
        others = loan.repayments.exclude(pk=self.pk) if self.pk else \
            loan.repayments.all()
        agg = others.aggregate(
            p=models.Sum('principal_paid'),
            i=models.Sum('interest_paid'),
            w=models.Sum('interest_waived'))
        other_principal = agg['p'] or Decimal('0')
        other_interest = (agg['i'] or Decimal('0')) + (agg['w'] or Decimal('0'))

        principal_paid = Decimal(self.principal_paid.amount or 0)
        interest_paid = Decimal(self.interest_paid.amount or 0)
        interest_waived = Decimal(self.interest_waived.amount or 0)

        remaining_principal = loan.principal.amount - other_principal
        if principal_paid - remaining_principal > tol:
            raise ValidationError({'principal_paid': _(
                'Principal paid (%(p)s) exceeds the outstanding principal '
                '(%(r)s) on this loan.') % {
                    'p': Money(principal_paid, cur),
                    'r': Money(max(remaining_principal, Decimal('0')), cur)}})

        remaining_interest = loan.interest_accrued().amount - other_interest
        if interest_paid + interest_waived - remaining_interest > tol:
            raise ValidationError({'interest_waived': _(
                'Interest paid + waived (%(s)s) exceeds the interest due '
                '(%(r)s) on this loan.') % {
                    's': Money(interest_paid + interest_waived, cur),
                    'r': Money(max(remaining_interest, Decimal('0')), cur)}})

    def save(self, *args, **kwargs):
        if not self.paid_at:
            self.paid_at = timezone.now()
        autogen_no = not self.receipt_no
        if autogen_no:
            self.receipt_no = self._next_receipt_no()
        if not autogen_no:
            super().save(*args, **kwargs)
            return
        # An auto-generated receipt_no is computed before insert, so concurrent
        # inserts can pick the same number; the uniq_receipt_no_per_tenant
        # constraint then rejects one. Regenerate and retry on collision.
        for attempt in range(_MAX_NO_RETRIES):
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                if attempt == _MAX_NO_RETRIES - 1:
                    raise
                self.receipt_no = self._next_receipt_no()

    def _next_receipt_no(self):
        """Generate a date-based receipt number: RCP-YYYYMMDD-NNN.

        NNN is a per-tenant daily counter based on the payment date.

        Uses an explicit datetime range (local-day start/end converted to
        the stored tz) rather than a ``paid_at__date`` lookup, since that
        lookup relies on MySQL CONVERT_TZ / timezone tables which are not
        guaranteed to be loaded.
        """
        import datetime as _dt
        from apps.core.tenancy import get_current_tenant
        tenant = self.tenant_id and self.tenant or get_current_tenant()
        local_dt = timezone.localtime(self.paid_at)
        pay_date = local_dt.date()
        prefix = f'RCP-{pay_date:%Y%m%d}-'
        if tenant is None:
            return f'{prefix}001'
        tz = local_dt.tzinfo
        day_start = timezone.make_aware(
            _dt.datetime.combine(pay_date, _dt.time.min), tz)
        day_end = day_start + _dt.timedelta(days=1)
        count = Repayment.all_objects.filter(
            tenant=tenant, paid_at__gte=day_start,
            paid_at__lt=day_end).count()
        return f'{prefix}{count + 1:03d}'

    def __str__(self):
        return f'{self.loan.loan_no} ₹{self.principal_paid + self.interest_paid}'
