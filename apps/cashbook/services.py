"""Cash book aggregation services. Tenant is always explicit so callers
work both from views (request.tenant) and from Celery / shell contexts.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import CashTransaction, DayClose


@dataclass
class CashPosition:
    on_date: date
    opening: Decimal
    inflow: Decimal
    outflow: Decimal
    closing: Decimal
    physical: Decimal
    variance: Decimal
    last_close_date: date | None


def _amt(qs):
    s = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    return Decimal(s)


def cash_position(tenant, on_date=None, branch=None) -> CashPosition:
    """Compute cash position for the day. opening = closing of most-recent
    DayClose before on_date (for this branch). inflow/outflow = sum of
    CashTransaction rows on on_date.

    `tenant=None` means platform-wide aggregation (super-admin view).
    """
    on_date = on_date or timezone.localdate()

    txn_qs = CashTransaction.all_objects.filter(txn_date=on_date)
    close_qs = DayClose.all_objects.filter(close_date__lt=on_date)
    today_close_qs = DayClose.all_objects.filter(close_date=on_date)
    if tenant is not None:
        txn_qs = txn_qs.filter(tenant=tenant)
        close_qs = close_qs.filter(tenant=tenant)
        today_close_qs = today_close_qs.filter(tenant=tenant)
    if branch is not None:
        txn_qs = txn_qs.filter(branch=branch)
        close_qs = close_qs.filter(branch=branch)
        today_close_qs = today_close_qs.filter(branch=branch)

    last_close = close_qs.order_by('-close_date').first()
    opening = last_close.closing_balance.amount if last_close else Decimal('0')

    inflow = _amt(txn_qs.filter(kind__in=list(CashTransaction.IN_KINDS)))
    outflow = _amt(txn_qs.filter(kind__in=list(CashTransaction.OUT_KINDS)))
    closing = opening + inflow - outflow

    today_close = today_close_qs.first()
    physical = today_close.physical_count.amount if today_close else closing
    variance = physical - closing

    return CashPosition(
        on_date=on_date,
        opening=opening.quantize(Decimal('0.01')),
        inflow=inflow.quantize(Decimal('0.01')),
        outflow=outflow.quantize(Decimal('0.01')),
        closing=closing.quantize(Decimal('0.01')),
        physical=physical.quantize(Decimal('0.01')),
        variance=variance.quantize(Decimal('0.01')),
        last_close_date=last_close.close_date if last_close else None,
    )


@dataclass
class CapitalBalance:
    capital_in:  Decimal  # owner injections (liability to owner)
    drawals:     Decimal  # owner takes out
    expenses:    Decimal  # operating expenses
    net_owner_liability: Decimal  # capital_in - drawals (still owed to owner)


def capital_balance(tenant) -> CapitalBalance:
    """Cumulative capital movements across all time, all branches.

    `tenant=None` → platform-wide sum across every broker.
    """
    qs = CashTransaction.all_objects.all()
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    capital_in = _amt(qs.filter(kind=CashTransaction.Kind.CAPITAL_IN))
    drawals    = _amt(qs.filter(kind=CashTransaction.Kind.DRAWAL_OUT))
    expenses   = _amt(qs.filter(kind=CashTransaction.Kind.EXPENSE_OUT))
    return CapitalBalance(
        capital_in=capital_in.quantize(Decimal('0.01')),
        drawals=drawals.quantize(Decimal('0.01')),
        expenses=expenses.quantize(Decimal('0.01')),
        net_owner_liability=(capital_in - drawals).quantize(Decimal('0.01')),
    )


def total_cash_on_hand(tenant) -> Decimal:
    """True running cash balance: for each branch, the most-recent day-close
    closing balance plus *every* cash transaction recorded after that close
    (or the sum of all transactions when the branch has never been closed).

    `tenant=None` → platform-wide across every branch.

    Note: this deliberately does NOT use cash_position(), which is scoped to a
    single day and silently drops any transaction between the last day-close
    and today. It also iterates every branch that has cash activity (not just
    active ones) so transactions on archived branches still count.
    """
    txn_qs = CashTransaction.all_objects.all()
    close_qs = DayClose.all_objects.all()
    if tenant is not None:
        txn_qs = txn_qs.filter(tenant=tenant)
        close_qs = close_qs.filter(tenant=tenant)

    branch_ids = (set(txn_qs.values_list('branch_id', flat=True))
                  | set(close_qs.values_list('branch_id', flat=True)))

    total = Decimal('0')
    for bid in branch_ids:
        b_txn = txn_qs.filter(branch_id=bid)
        last_close = close_qs.filter(branch_id=bid).order_by('-close_date').first()
        if last_close is not None:
            opening = last_close.closing_balance.amount
            b_txn = b_txn.filter(txn_date__gt=last_close.close_date)
        else:
            opening = Decimal('0')
        inflow = _amt(b_txn.filter(kind__in=list(CashTransaction.IN_KINDS)))
        outflow = _amt(b_txn.filter(kind__in=list(CashTransaction.OUT_KINDS)))
        total += opening + inflow - outflow
    return total.quantize(Decimal('0.01'))


# ---------- denomination helpers ------------------------------------------

DEFAULT_DENOMS = [2000, 500, 200, 100, 50, 20, 10, 5, 2, 1]


def denom_total(denom_dict) -> Decimal:
    """Sum a {denom: count} dict to a rupee total."""
    total = Decimal('0')
    for d, n in (denom_dict or {}).items():
        try:
            total += Decimal(int(d)) * Decimal(int(n))
        except (TypeError, ValueError):
            continue
    return total
