from functools import wraps
from decimal import Decimal

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .models import Customer
from apps.core.permissions import role_can, R


def _allowed(request, customer):
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant is None or not request.user.is_staff:
        return False
    if customer.tenant_id != tenant.id or request.user.tenant_id != tenant.id:
        return False
    return role_can(request.user, 'customer', R)


@staff_member_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer.all_objects, pk=pk)
    if not _allowed(request, customer):
        return HttpResponseForbidden('Not allowed.')

    loans = customer.loans.all().order_by('-start_date')
    active_loans = [l for l in loans if l.status in ('active', 'overdue')]
    closed_loans = [l for l in loans if l.status in ('closed', 'auctioned')]

    total_outstanding = sum((l.outstanding_principal().amount for l in active_loans),
                            Decimal('0'))
    total_interest_due = sum((l.interest_due_now().amount for l in active_loans),
                             Decimal('0'))
    lifetime_borrowed = sum((l.principal.amount for l in loans), Decimal('0'))
    lifetime_interest_paid = sum(
        (l.total_paid_interest().amount for l in loans), Decimal('0'))
    lifetime_interest_waived = sum(
        (l.total_waived_interest().amount for l in loans), Decimal('0'))

    # Recent activity: combine loans + repayments timeline
    events = []
    for L in loans:
        events.append({'when': L.start_date, 'icon': 'account_balance_wallet',
                       'kind': 'loan',
                       'title': f'Loan {L.loan_no} disbursed',
                       'desc': f'Principal ₹{L.principal.amount:,.2f} @ '
                               f'{L.interest_rate_pct}% '
                               f'{"p.m." if L.rate_type == "monthly" else "p.a."}'})
        for r in L.repayments.all():
            tot = r.principal_paid.amount + r.interest_paid.amount
            events.append({'when': r.paid_at.date(), 'icon': 'payments',
                           'kind': 'repayment',
                           'title': f'Repayment of ₹{tot:,.2f} on {L.loan_no}',
                           'desc': f'Principal ₹{r.principal_paid.amount:,.2f}'
                                   f' + Interest ₹{r.interest_paid.amount:,.2f}'
                                   f' via {r.get_mode_display()}'})
    events.sort(key=lambda e: str(e['when']), reverse=True)

    context = {
        **admin.site.each_context(request),
        'customer': customer,
        'loans': loans,
        'active_loans': active_loans,
        'closed_loans': closed_loans,
        'total_outstanding': total_outstanding,
        'total_interest_due': total_interest_due,
        'lifetime_borrowed': lifetime_borrowed,
        'lifetime_interest_paid': lifetime_interest_paid,
        'lifetime_interest_waived': lifetime_interest_waived,
        'events': events[:20],
        'edit_url': reverse('admin:customers_customer_change', args=[customer.pk]),
        'add_loan_url': reverse('admin:loans_loan_add')
                        + f'?customer={customer.pk}',
        'whatsapp_url': customer.whatsapp_link(),
        'title': f'{customer.code} — {customer.name}',
    }
    return render(request, 'customers/detail.html', context)
