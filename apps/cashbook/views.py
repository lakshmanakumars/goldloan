"""Cash book custom views: day-close form + position dashboard."""
from datetime import date as _date
from decimal import Decimal

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from djmoney.money import Money

from apps.core.permissions import role_can, R, W
from apps.iam.models import Branch
from .models import CashTransaction, DayClose
from .services import cash_position, capital_balance, total_cash_on_hand, \
                      DEFAULT_DENOMS, denom_total


def _allowed(request, mode=R):
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant is None or not request.user.is_staff:
        return False
    if request.user.tenant_id != tenant.id:
        return False
    return role_can(request.user, 'cashbook', mode)


@staff_member_required
def day_close_form(request):
    if not _allowed(request, W):
        return HttpResponseForbidden('Not allowed.')
    tenant = request.tenant

    today = timezone.localdate()
    branch_id = request.GET.get('branch') or request.POST.get('branch')
    branches = list(Branch.objects.filter(tenant=tenant, is_active=True))
    branch = None
    if branch_id:
        branch = next((b for b in branches if str(b.pk) == str(branch_id)), None)
    branch = branch or Branch.default_for(tenant) or (branches[0] if branches else None)

    if branch is None:
        messages.error(request, 'No active branch found for this tenant.')
        return redirect(reverse('admin:index'))

    pos = cash_position(tenant, on_date=today, branch=branch)

    if request.method == 'POST':
        denoms = {}
        for d in DEFAULT_DENOMS:
            v = request.POST.get(f'd_{d}', '').strip()
            try:
                cnt = int(v) if v else 0
            except ValueError:
                cnt = 0
            if cnt:
                denoms[str(d)] = cnt
        physical = denom_total(denoms) or Decimal(
            request.POST.get('physical_override') or pos.closing)
        existing = DayClose.all_objects.filter(
            tenant=tenant, branch=branch, close_date=today).first()
        close = existing or DayClose(tenant=tenant, branch=branch,
                                     close_date=today)
        close.physical_count = Money(physical, 'INR')
        close.denomination_json = denoms
        close.notes = request.POST.get('notes', '').strip()
        # Computed fields filled in save_model — emulate here for direct save
        close.opening_balance = Money(pos.opening, 'INR')
        close.computed_in = Money(pos.inflow, 'INR')
        close.computed_out = Money(pos.outflow, 'INR')
        close.closing_balance = Money(pos.closing, 'INR')
        close.variance = Money(physical - pos.closing, 'INR')
        if not close.closed_by_id:
            close.closed_by = request.user
        close.save()
        messages.success(request,
            f'Day closed for {branch.code} on {today}: '
            f'closing ₹{pos.closing:,.2f}, '
            f'variance ₹{(physical - pos.closing):+,.2f}')
        return redirect(reverse('admin:cashbook_dayclose_changelist'))

    context = {
        **admin.site.each_context(request),
        'title': f'Day Close — {today}',
        'today': today,
        'branch': branch,
        'branches': branches,
        'pos': pos,
        'denoms': DEFAULT_DENOMS,
        'denom_existing': {},
    }
    return render(request, 'cashbook/day_close.html', context)


@staff_member_required
def cash_book_detail(request):
    if not _allowed(request, R):
        return HttpResponseForbidden('Not allowed.')
    tenant = request.tenant

    on_date_str = request.GET.get('date')
    try:
        on_date = _date.fromisoformat(on_date_str) if on_date_str else timezone.localdate()
    except ValueError:
        on_date = timezone.localdate()

    branch_id = request.GET.get('branch')
    # Super-admin (tenant=None) sees branches across every tenant
    br_qs = Branch.objects.filter(is_active=True).select_related('tenant')
    if tenant is not None:
        br_qs = br_qs.filter(tenant=tenant)
    branches = list(br_qs.order_by('tenant__slug', 'code'))
    branch = None
    if branch_id:
        branch = next((b for b in branches if str(b.pk) == str(branch_id)), None)

    pos = cash_position(tenant, on_date=on_date, branch=branch)
    cap = capital_balance(tenant)
    total_cash = total_cash_on_hand(tenant)

    # Use unscoped manager when tenant is None so super-admin sees all rows;
    # tenant view uses the auto-scoped default manager.
    if tenant is None:
        txn_qs = CashTransaction.all_objects.filter(txn_date=on_date)
    else:
        txn_qs = CashTransaction.objects.filter(txn_date=on_date)
    if branch is not None:
        txn_qs = txn_qs.filter(branch=branch)
    transactions = txn_qs.select_related(
        'source_loan__customer', 'source_repayment__loan__customer',
        'branch', 'tenant').order_by('-id')

    context = {
        **admin.site.each_context(request),
        'title': f'Cash Book — {on_date}',
        'on_date': on_date,
        'branch': branch,
        'branches': branches,
        'pos': pos,
        'cap': cap,
        'total_cash': total_cash,
        'transactions': transactions,
        'day_close_url': reverse('cashbook:day_close'),
        'add_txn_url': reverse('admin:cashbook_cashtransaction_add'),
    }
    return render(request, 'cashbook/detail.html', context)
