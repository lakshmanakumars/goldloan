"""PDF generation: pledge ticket + repayment receipt.

Uses WeasyPrint. Bilingual (English + customer's preferred language) where
the customer has a regional language preference; English-only otherwise.

Permissions: any authenticated tenant staff for the loan/repayment that
belongs to their tenant. Super-admin can view any.
"""
from decimal import Decimal
from functools import wraps

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.http import (
    HttpResponse, HttpResponseForbidden, Http404, JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from weasyprint import HTML

from .models import Loan, Repayment
from apps.core.permissions import role_can, R


def _allowed(request, obj):
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant is None or not request.user.is_staff:
        return False
    return obj.tenant_id == tenant.id and request.user.tenant_id == tenant.id


def tenant_pdf(view):
    @wraps(view)
    @staff_member_required
    def wrapper(request, pk, *args, **kwargs):
        return view(request, pk, *args, **kwargs)
    return wrapper


@staff_member_required
def loan_balance_json(request, pk):
    """JSON for the repayment-admin autofill JS.

    Returns the loan's outstanding principal and interest-due-now, so the
    Repayment add-form can pre-fill the amount fields when a loan is picked.
    """
    loan = Loan.all_objects.filter(pk=pk).only(
        'id', 'tenant_id', 'principal', 'principal_currency',
        'start_date', 'interest_rate_pct', 'rate_type',
    ).first()
    if loan is None:
        raise Http404
    if not _allowed(request, loan):
        return HttpResponseForbidden('Not allowed.')
    interest_due = loan.interest_due_now().amount
    outstanding = loan.outstanding_principal().amount
    monthly = loan.monthly_interest().amount
    return JsonResponse({
        'loan_no': loan.loan_no,
        'currency': str(loan.principal.currency),
        'principal': str(loan.principal.amount),
        'outstanding_principal': str(outstanding),
        'monthly_interest': str(monthly),
        'interest_due_now': str(interest_due),
        'months_charged': loan.months_charged(),
        'days_outstanding': loan.days_outstanding(),
    })


@tenant_pdf
def pledge_ticket_pdf(request, pk):
    loan = Loan.all_objects.filter(pk=pk).select_related(
        'tenant', 'customer').prefetch_related('items').first()
    if loan is None:
        raise Http404
    if not _allowed(request, loan):
        return HttpResponseForbidden('Not allowed.')

    secondary = (loan.customer.preferred_language or 'en-in')
    if secondary == 'en-in':
        secondary = None  # English only; no second column needed

    total_net_wt = sum((Decimal(i.net_weight_g) for i in loan.items.all()),
                       Decimal('0'))

    html_str = render_to_string('loans/pledge_ticket.html', {
        'loan': loan,
        'customer': loan.customer,
        'tenant': loan.tenant,
        'items': loan.items.all(),
        'total_net_wt': total_net_wt,
        'monthly_interest': loan.monthly_interest(),
        'annual_rate': loan.annual_rate_pct,
        'today': timezone.now().date(),
        'secondary_lang': secondary,
    })
    pdf_bytes = HTML(string=html_str).write_pdf()
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = \
        f'inline; filename="pledge-{loan.loan_no}.pdf"'
    return response


# ---- HTML detail pages -------------------------------------------------

@staff_member_required
def loan_detail(request, pk):
    loan = get_object_or_404(Loan.all_objects, pk=pk)
    if not _allowed(request, loan):
        return HttpResponseForbidden('Not allowed.')

    items = loan.items.all()
    repayments = loan.repayments.all().order_by('paid_at')
    ltv = loan.ltv_breakdown()

    paid_p = loan.total_paid_principal().amount
    paid_i = loan.total_paid_interest().amount
    waived_i = loan.total_waived_interest().amount
    outstanding = loan.outstanding_principal().amount
    monthly = loan.monthly_interest().amount
    accrued = loan.interest_accrued().amount
    due_now = loan.interest_due_now().amount
    days = loan.days_outstanding()
    months = loan.months_charged()

    # Timeline events
    events = [{
        'when': loan.start_date, 'icon': 'account_balance_wallet',
        'title': f'Loan {loan.loan_no} disbursed',
        'desc': f'₹{loan.principal.amount:,.2f} at {loan.interest_rate_pct}% '
                f'{"p.m." if loan.rate_type == "monthly" else "p.a."}',
    }]
    for r in repayments:
        events.append({
            'when': r.paid_at.date(), 'icon': 'payments',
            'title': f'Repayment ₹{r.principal_paid.amount + r.interest_paid.amount:,.2f}',
            'desc': f'Principal ₹{r.principal_paid.amount:,.2f} + '
                    f'Interest ₹{r.interest_paid.amount:,.2f} via '
                    f'{r.get_mode_display()}'
                    + (f' (ref {r.reference})' if r.reference else ''),
            'extra_url': reverse('loans:repayment_detail', args=[r.pk]),
        })
    if loan.closed_at:
        events.append({
            'when': loan.closed_at.date(), 'icon': 'lock',
            'title': f'Loan closed', 'desc': loan.get_status_display(),
        })
    events.sort(key=lambda e: str(e['when']))

    can_edit = role_can(request.user, 'loan', 'w')
    can_repay = role_can(request.user, 'repayment', 'w')
    is_open = loan.status in (Loan.Status.ACTIVE, Loan.Status.OVERDUE)

    return render(request, 'loans/detail.html', {
        **admin.site.each_context(request),
        'loan': loan, 'items': items, 'repayments': repayments,
        'ltv': ltv,
        'paid_p': paid_p, 'paid_i': paid_i, 'waived_i': waived_i,
        'outstanding': outstanding,
        'monthly': monthly, 'accrued': accrued, 'due_now': due_now,
        'days': days, 'months': months,
        'total_settlement': outstanding + due_now,
        'events': events,
        'is_open': is_open,
        'can_edit': can_edit, 'can_repay': can_repay,
        'edit_url': reverse('admin:loans_loan_change', args=[loan.pk]),
        'history_url': reverse('admin:loans_loan_history', args=[loan.pk]),
        'pledge_pdf_url': reverse('loans:pledge_ticket', args=[loan.pk]),
        'whatsapp_url': loan.whatsapp_reminder_link(),
        'add_repayment_url': reverse('admin:loans_repayment_add')
                             + f'?loan={loan.pk}',
        'preclose_url': reverse('loans:preclose', args=[loan.pk]),
        'renew_url': reverse('loans:renew', args=[loan.pk]),
        'topup_url': reverse('loans:topup', args=[loan.pk]),
        'ltv_within': loan.principal.amount <= ltv['eligible_principal'],
        'title': f'Loan {loan.loan_no}',
    })


@staff_member_required
def repayment_detail(request, pk):
    rp = get_object_or_404(Repayment.all_objects, pk=pk)
    if not _allowed(request, rp):
        return HttpResponseForbidden('Not allowed.')
    loan = rp.loan
    paid_p_running = loan.repayments.filter(paid_at__lte=rp.paid_at).aggregate(
        s=Sum('principal_paid'))['s'] or Decimal('0')
    outstanding_after = loan.principal.amount - paid_p_running

    return render(request, 'loans/repayment_detail.html', {
        **admin.site.each_context(request),
        'rp': rp, 'loan': loan, 'customer': loan.customer,
        'outstanding_after': outstanding_after,
        'pdf_url': reverse('loans:repayment_receipt', args=[rp.pk]),
        'loan_url': reverse('loans:detail', args=[loan.pk]),
        'customer_url': reverse('customers:detail', args=[loan.customer.pk]),
        'edit_url': reverse('admin:loans_repayment_change', args=[rp.pk]),
        'whatsapp_url': loan.customer.whatsapp_link(
            f'Receipt for ₹{rp.principal_paid.amount + rp.interest_paid.amount:.2f} '
            f'received against loan {loan.loan_no}. Outstanding ₹{outstanding_after:.2f}. - {loan.tenant.name}'),
        'title': f'Receipt {rp.receipt_no or rp.pk}',
    })


@tenant_pdf
def repayment_receipt_pdf(request, pk):
    rp = Repayment.all_objects.filter(pk=pk).select_related(
        'tenant', 'loan', 'loan__customer').first()
    if rp is None:
        raise Http404
    if not _allowed(request, rp):
        return HttpResponseForbidden('Not allowed.')

    loan = rp.loan
    paid_p = loan.repayments.filter(paid_at__lte=rp.paid_at).aggregate(
        s=Sum('principal_paid'))['s'] or Decimal('0')
    outstanding_after = loan.principal.amount - paid_p

    secondary = (loan.customer.preferred_language or 'en-in')
    if secondary == 'en-in':
        secondary = None

    html_str = render_to_string('loans/repayment_receipt.html', {
        'rp': rp,
        'loan': loan,
        'customer': loan.customer,
        'tenant': loan.tenant,
        'outstanding_after': outstanding_after,
        'secondary_lang': secondary,
    })
    pdf_bytes = HTML(string=html_str).write_pdf()
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = \
        f'inline; filename="receipt-{rp.receipt_no or rp.pk}.pdf"'
    return response
