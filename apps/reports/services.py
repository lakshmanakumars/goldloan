"""Pure aggregation logic for reports.

All functions accept an explicit tenant (or None for platform-wide) so they
work both from request-driven views and from shell / Celery contexts.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from apps.loans.models import Loan, Repayment


# ---------- helpers ----------

def _local_dt_range(from_date, to_date):
    """Half-open aware-datetime range [start, end) covering the local dates
    from_date..to_date inclusive.

    We compare paid_at against plain datetime bounds instead of using
    ``paid_at__date`` lookups: on MySQL the ``__date`` lookup wraps the column
    in ``CONVERT_TZ(...)``, which returns NULL when the server's named
    timezone tables aren't loaded, so the filter would silently match nothing.
    A direct datetime comparison needs no CONVERT_TZ.
    """
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(from_date, time.min), tz)
    end = timezone.make_aware(
        datetime.combine(to_date + timedelta(days=1), time.min), tz)
    return start, end


def _money(amount, currency='INR'):
    from djmoney.money import Money
    return Money(Decimal(amount or 0).quantize(Decimal('0.01')), currency)


def _qs_loans(tenant):
    qs = Loan.all_objects.all()
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    return qs


def _qs_repayments(tenant):
    qs = Repayment.all_objects.all()
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    return qs


# ---------- KPIs ----------

@dataclass
class KPI:
    active_loans: int
    overdue_loans: int
    closed_loans: int
    outstanding_principal: Decimal
    lifetime_disbursed: Decimal
    lifetime_received_principal: Decimal
    lifetime_received_interest: Decimal
    lifetime_waived_interest: Decimal
    interest_this_month: Decimal
    waived_this_month: Decimal
    loanbook_networth: Decimal


@dataclass
class Networth:
    """True networth components (uses Cash Book when available)."""
    loan_book_outstanding: Decimal       # active+overdue principals
    accrued_unpaid_interest: Decimal     # interest_due_now summed
    cash_on_hand: Decimal                # sum of latest DayClose per branch
    capital_injected: Decimal            # owner money put in (liability)
    owner_drawals: Decimal               # owner money taken out
    expenses: Decimal                    # operating expenses paid
    lifetime_interest_earned: Decimal    # for cumulative profit display
    total_networth: Decimal              # the headline number
    cash_book_available: bool            # False if no Cash Book data yet


def compute_kpis(tenant=None) -> KPI:
    loans = _qs_loans(tenant)
    repays = _qs_repayments(tenant)

    today = timezone.now().date()
    month_start = today.replace(day=1)

    active = loans.filter(status=Loan.Status.ACTIVE).count()
    overdue = loans.filter(status=Loan.Status.OVERDUE).count()
    closed = loans.filter(status=Loan.Status.CLOSED).count()

    lifetime_disbursed = loans.aggregate(s=Sum('principal'))['s'] or Decimal('0')
    paid_principal = repays.aggregate(s=Sum('principal_paid'))['s'] or Decimal('0')
    paid_interest = repays.aggregate(s=Sum('interest_paid'))['s'] or Decimal('0')
    waived_interest = repays.aggregate(
        s=Sum('interest_waived'))['s'] or Decimal('0')
    month_start_dt, _ = _local_dt_range(month_start, month_start)
    interest_month = repays.filter(paid_at__gte=month_start_dt).aggregate(
        s=Sum('interest_paid'))['s'] or Decimal('0')
    waived_month = repays.filter(paid_at__gte=month_start_dt).aggregate(
        s=Sum('interest_waived'))['s'] or Decimal('0')

    outstanding = lifetime_disbursed - paid_principal

    # Loan-book Networth = outstanding principal + interest accrued-but-unpaid
    # on every live loan. interest_due_now() applies the day-based accrual
    # (flat first 30 days, then pro-rated) and nets off interest already paid,
    # so this stays consistent with compute_networth().
    accrued_unpaid = Decimal('0')
    for loan in loans.filter(
            status__in=[Loan.Status.ACTIVE, Loan.Status.OVERDUE]):
        accrued_unpaid += loan.interest_due_now().amount

    networth = outstanding + accrued_unpaid

    return KPI(
        active_loans=active,
        overdue_loans=overdue,
        closed_loans=closed,
        outstanding_principal=outstanding.quantize(Decimal('0.01')),
        lifetime_disbursed=lifetime_disbursed.quantize(Decimal('0.01')),
        lifetime_received_principal=paid_principal.quantize(Decimal('0.01')),
        lifetime_received_interest=paid_interest.quantize(Decimal('0.01')),
        lifetime_waived_interest=waived_interest.quantize(Decimal('0.01')),
        interest_this_month=interest_month.quantize(Decimal('0.01')),
        waived_this_month=waived_month.quantize(Decimal('0.01')),
        loanbook_networth=networth.quantize(Decimal('0.01')),
    )


def compute_networth(tenant) -> Networth:
    """True networth = loan book + accrued interest + cash on hand
    − capital injected − owner drawals − expenses + lifetime interest earned.

    Tenant must be specified (platform-wide networth doesn't make sense
    when each tenant has its own cash).
    """
    from apps.cashbook.services import total_cash_on_hand, capital_balance
    from apps.cashbook.models import CashTransaction

    loans = _qs_loans(tenant)
    repays = _qs_repayments(tenant)

    active_loans = list(loans.filter(
        status__in=[Loan.Status.ACTIVE, Loan.Status.OVERDUE]
    ))
    outstanding = sum(
        (L.outstanding_principal().amount for L in active_loans),
        Decimal('0'))
    accrued = sum(
        (L.interest_due_now().amount for L in active_loans), Decimal('0'))

    cash_available = CashTransaction.all_objects.filter(tenant=tenant).exists()
    cash = total_cash_on_hand(tenant) if cash_available else Decimal('0')

    cap = capital_balance(tenant)
    interest_earned = repays.aggregate(
        s=Sum('interest_paid'))['s'] or Decimal('0')

    # Networth = total assets − total liabilities.
    #
    #   Assets      = loan book outstanding + accrued interest receivable + cash
    #   Liabilities = net capital owed to owner = capital_injected − drawals
    #
    #   net = outstanding + accrued + cash − (capital_in − drawals)
    #       = outstanding + accrued + cash − capital_in + drawals
    #
    # Collected interest and paid expenses are NOT separate terms: they have
    # already flowed through `cash` (interest received raised cash, expenses
    # lowered it). Adding interest_earned or subtracting expenses again would
    # double-count them. Likewise drawals already lowered cash, so they are
    # *added back* here because they reduce what the business still owes the
    # owner.
    net = (outstanding + accrued + cash
           - cap.capital_in + cap.drawals)

    return Networth(
        loan_book_outstanding=outstanding.quantize(Decimal('0.01')),
        accrued_unpaid_interest=accrued.quantize(Decimal('0.01')),
        cash_on_hand=cash.quantize(Decimal('0.01')),
        capital_injected=cap.capital_in,
        owner_drawals=cap.drawals,
        expenses=cap.expenses,
        lifetime_interest_earned=interest_earned.quantize(Decimal('0.01')),
        total_networth=net.quantize(Decimal('0.01')),
        cash_book_available=cash_available,
    )


# ---------- Daily Cash Book ----------

@dataclass
class CashRow:
    when: str
    kind: str   # 'OUT' (disbursement) or 'IN' (repayment)
    ref: str
    party: str
    note: str
    amount_out: Decimal
    amount_in: Decimal
    running: Decimal


def daily_cash_book(tenant, on_date=None):
    on_date = on_date or timezone.now().date()
    loans = _qs_loans(tenant).filter(start_date=on_date).select_related('customer')
    day_start, day_end = _local_dt_range(on_date, on_date)
    repays = _qs_repayments(tenant).filter(
        paid_at__gte=day_start, paid_at__lt=day_end,
    ).select_related('loan__customer')

    events = []
    for loan in loans:
        events.append(('out', loan.start_date, loan))
    for r in repays:
        events.append(('in', r.paid_at, r))
    events.sort(key=lambda e: (str(e[1]), 0 if e[0] == 'out' else 1))

    rows, running = [], Decimal('0')
    total_out = total_in = Decimal('0')
    for kind, when, obj in events:
        if kind == 'out':
            amt_out = obj.principal.amount
            amt_in = Decimal('0')
            ref = obj.loan_no
            party = obj.customer.name
            note = 'Loan disbursed'
        else:
            amt_in = obj.principal_paid.amount + obj.interest_paid.amount
            amt_out = Decimal('0')
            ref = obj.loan.loan_no
            party = obj.loan.customer.name
            note = f'Repayment ({obj.get_mode_display()})'
        running += amt_in - amt_out
        total_out += amt_out
        total_in += amt_in
        rows.append(CashRow(
            when=str(when),
            kind='OUT' if kind == 'out' else 'IN',
            ref=ref, party=party, note=note,
            amount_out=amt_out, amount_in=amt_in, running=running,
        ))
    return {
        'date': on_date,
        'rows': rows,
        'total_out': total_out,
        'total_in': total_in,
        'net': total_in - total_out,
    }


# ---------- Monthly Cash Summary ----------

def monthly_cash_summary(tenant, year=None):
    """Aggregate disbursements + repayments by calendar month.

    Done in Python (not via TruncMonth) so we don't depend on MySQL's
    timezone tables being populated.
    """
    year = year or timezone.localdate().year
    months = {}
    for i in range(1, 13):
        months[i] = {'month': date(year, i, 1), 'out': Decimal('0'),
                     'in': Decimal('0'), 'interest': Decimal('0'),
                     'waived': Decimal('0')}

    for loan in _qs_loans(tenant).filter(start_date__year=year):
        months[loan.start_date.month]['out'] += loan.principal.amount

    for r in _qs_repayments(tenant).filter(paid_at__year=year):
        # paid_at is tz-aware; convert to local date for month bucket
        m = timezone.localtime(r.paid_at).month
        months[m]['in'] += r.principal_paid.amount + r.interest_paid.amount
        months[m]['interest'] += r.interest_paid.amount
        months[m]['waived'] += r.interest_waived.amount

    rows = list(months.values())
    return {
        'year': year,
        'rows': rows,
        'total_out': sum(r['out'] for r in rows),
        'total_in': sum(r['in'] for r in rows),
        'total_interest': sum(r['interest'] for r in rows),
        'total_waived': sum(r['waived'] for r in rows),
    }


# ---------- Outstanding Portfolio ----------

def outstanding_portfolio(tenant):
    loans = _qs_loans(tenant).filter(
        status__in=[Loan.Status.ACTIVE, Loan.Status.OVERDUE],
    ).select_related('customer').order_by('-start_date')

    rows = []
    today = timezone.now().date()
    for loan in loans:
        paid_p = loan.repayments.aggregate(
            s=Sum('principal_paid'))['s'] or Decimal('0')
        paid_i = loan.repayments.aggregate(
            s=Sum('interest_paid'))['s'] or Decimal('0')
        outstanding = loan.principal.amount - paid_p
        days = (today - loan.start_date).days
        rows.append({
            'loan_no': loan.loan_no,
            'customer': loan.customer.name,
            'customer_phone': loan.customer.phone,
            'principal': loan.principal.amount,
            'paid_principal': paid_p,
            'paid_interest': paid_i,
            'outstanding': outstanding,
            'start_date': loan.start_date,
            'maturity_date': loan.maturity_date,
            'days_outstanding': days,
            'status': loan.get_status_display(),
            'rate': f'{loan.interest_rate_pct}% '
                    f'{"p.m." if loan.rate_type == loan.RateType.MONTHLY else "p.a."}',
        })
    return {
        'rows': rows,
        'total_principal': sum(r['principal'] for r in rows),
        'total_outstanding': sum(r['outstanding'] for r in rows),
    }


# ---------- Interest Earned ----------

def interest_earned(tenant, from_date, to_date):
    start_dt, end_dt = _local_dt_range(from_date, to_date)
    repays = _qs_repayments(tenant).filter(
        paid_at__gte=start_dt,
        paid_at__lt=end_dt,
    ).select_related('loan__customer').order_by('paid_at')

    rows = []
    total = Decimal('0')
    total_waived = Decimal('0')
    for r in repays:
        if r.interest_paid.amount > 0 or r.interest_waived.amount > 0:
            rows.append({
                'paid_at': r.paid_at,
                'loan_no': r.loan.loan_no,
                'customer': r.loan.customer.name,
                'amount': r.interest_paid.amount,
                'waived': r.interest_waived.amount,
                'mode': r.get_mode_display(),
                'receipt_no': r.receipt_no,
            })
            total += r.interest_paid.amount
            total_waived += r.interest_waived.amount
    return {
        'from_date': from_date,
        'to_date': to_date,
        'rows': rows,
        'total': total,
        'total_waived': total_waived,
    }


# ---------- Customer Statement ----------

def customer_statement(tenant, customer_id):
    from apps.customers.models import Customer
    customer = Customer.all_objects.get(pk=customer_id, tenant=tenant)

    loans = customer.loans.all().order_by('start_date')
    events = []
    for loan in loans:
        events.append({
            'when': loan.start_date,
            'event': f'Loan {loan.loan_no} disbursed',
            'out': loan.principal.amount, 'in': Decimal('0'),
        })
        for r in loan.repayments.all().order_by('paid_at'):
            events.append({
                'when': r.paid_at.date(),
                'event': f'Repayment to {loan.loan_no} '
                         f'(P:{r.principal_paid.amount} I:{r.interest_paid.amount})',
                'out': Decimal('0'),
                'in': r.principal_paid.amount + r.interest_paid.amount,
            })
    events.sort(key=lambda e: str(e['when']))
    running = Decimal('0')
    for e in events:
        running += e['out'] - e['in']
        e['balance'] = running

    return {
        'customer': customer,
        'events': events,
        'total_out': sum(e['out'] for e in events),
        'total_in': sum(e['in'] for e in events),
        'balance': running,
    }


# ---------- Super-admin: per-broker snapshot ----------

def broker_snapshot():
    from apps.iam.models import Tenant
    rows = []
    for tenant in Tenant.objects.all().order_by('name'):
        k = compute_kpis(tenant)
        rows.append({
            'tenant': tenant,
            'active': k.active_loans,
            'overdue': k.overdue_loans,
            'disbursed': k.lifetime_disbursed,
            'received': k.lifetime_received_principal + k.lifetime_received_interest,
            'outstanding': k.outstanding_principal,
            'interest_earned': k.lifetime_received_interest,
            'networth': k.loanbook_networth,
        })
    return {
        'rows': rows,
        'totals': {
            'disbursed': sum(r['disbursed'] for r in rows),
            'received': sum(r['received'] for r in rows),
            'outstanding': sum(r['outstanding'] for r in rows),
            'interest': sum(r['interest_earned'] for r in rows),
            'networth': sum(r['networth'] for r in rows),
        },
    }
