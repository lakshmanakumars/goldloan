"""Loan lifecycle workflow actions: pre-close, renew, top-up.

All three are intermediate views — they show a small form, then on POST
they mutate the loan (and create a new one for renew / top-up). Permissions:
any tenant staff member on a loan that belongs to their tenant.
"""
from decimal import Decimal
from functools import wraps

from dateutil.relativedelta import relativedelta
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from djmoney.money import Money

from .models import Loan, GoldItem


def _allowed(request, loan):
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant is None or not request.user.is_staff:
        return False
    return loan.tenant_id == tenant.id and request.user.tenant_id == tenant.id


def _back_to_loan_list():
    return redirect(reverse('admin:loans_loan_changelist'))


def _back_to_loan(pk):
    return redirect(reverse('admin:loans_loan_change', args=[pk]))


def _ltv_ctx(loan):
    """LTV figures for the renew/top-up forms.

    ``headroom`` = how much principal can still be lent within the tenant's
    LTV cap on the current gold value; negative means already over-LTV.
    """
    ltv = loan.ltv_breakdown()
    headroom = ltv['eligible_principal'] - loan.outstanding_principal().amount
    return {'ltv': ltv, 'ltv_headroom': headroom}


def _action_blockers(loan, new_principal=None):
    """Hard-stop reasons that forbid a renew/top-up. Returns a list of
    human-readable strings (empty = allowed).

    Two independent gates:
      1. Unpaid interest on the loan must be cleared first.
      2. The resulting principal must stay within the LTV cap.

    ``new_principal`` defaults to the carried-forward outstanding (renew);
    top-up passes outstanding + extra.
    """
    errors = []
    due = loan.interest_due_now().amount
    if due > 0:
        errors.append(
            f'Interest of ₹{due:.2f} is unpaid on {loan.loan_no}. '
            f'Record it as a Repayment before you can proceed.')
    eligible = loan.ltv_breakdown()['eligible_principal']
    principal = (new_principal if new_principal is not None
                 else loan.outstanding_principal().amount)
    if principal > eligible:
        errors.append(
            f'New principal ₹{principal:.2f} exceeds the LTV-eligible '
            f'₹{eligible:.2f} ({loan.tenant.max_ltv_pct}% cap). '
            f'Reduce the amount or add collateral.')
    return errors


def loan_action(view):
    @wraps(view)
    @staff_member_required
    def wrapper(request, pk, *args, **kwargs):
        loan = get_object_or_404(Loan.all_objects, pk=pk)
        if not _allowed(request, loan):
            return HttpResponseForbidden('Not allowed.')
        if loan.status in (Loan.Status.CLOSED, Loan.Status.AUCTIONED):
            messages.warning(request,
                f'Loan {loan.loan_no} is already {loan.get_status_display()}.')
            return _back_to_loan(pk)
        return view(request, loan, *args, **kwargs)
    return wrapper


# ---------- PRE-CLOSE ----------

@loan_action
def preclose_loan(request, loan):
    if request.method == 'POST':
        with transaction.atomic():
            loan.status = Loan.Status.CLOSED
            loan.closed_at = timezone.now()
            loan.save()
        messages.success(request,
            f'Loan {loan.loan_no} pre-closed. Record any settlement payment '
            f'as a Repayment under that loan.')
        return _back_to_loan(loan.pk)

    return render(request, 'loans/action_confirm.html', {
        **admin.site.each_context(request),
        'action': 'preclose',
        'title': f'Pre-close loan {loan.loan_no}',
        'loan': loan,
        'message': (
            f'Mark loan <b>{loan.loan_no}</b> for <b>{loan.customer.name}</b> '
            f'as <b>closed</b>?<br><br>'
            f'Outstanding principal: ₹{loan.outstanding_principal().amount:.2f}<br>'
            f'Interest due now: ₹{loan.interest_due_now().amount:.2f}<br>'
            f'<b>Total to settle: '
            f'₹{loan.outstanding_principal().amount + loan.interest_due_now().amount:.2f}'
            f'</b><br><br>'
            f'Record this settlement as a Repayment on this loan '
            f'<i>before</i> closing it, or it will be lost from the books.'
        ),
        'submit_label': 'Confirm pre-close',
        'submit_class': 'btn-danger',
    })


# ---------- RENEW ----------

@loan_action
def renew_loan(request, loan):
    if request.method == 'POST':
        tenure_months = int(request.POST.get('tenure_months') or 12)
        rate_pct = Decimal(request.POST.get('interest_rate_pct')
                           or str(loan.interest_rate_pct))
        rate_type = request.POST.get('rate_type') or loan.rate_type
        start_date = timezone.now().date()

        blockers = _action_blockers(loan)  # renew keeps outstanding as principal
        if blockers:
            for e in blockers:
                messages.error(request, e)
            return redirect(reverse('loans:renew', args=[loan.pk]))

        with transaction.atomic():
            new_loan = Loan(
                customer=loan.customer,
                principal=Money(loan.outstanding_principal().amount, 'INR'),
                rate_type=rate_type,
                interest_rate_pct=rate_pct,
                tenure_months=tenure_months,
                start_date=start_date,
                maturity_date=start_date + relativedelta(months=tenure_months),
                packet_no=loan.packet_no,
                purpose=loan.purpose,
                notes=f'Renewed from {loan.loan_no} on {start_date}.',
                status=Loan.Status.ACTIVE,
            )
            new_loan.save()
            # Copy gold items
            for it in loan.items.all():
                GoldItem.objects.create(
                    loan=new_loan,
                    description=it.description,
                    gross_weight_g=it.gross_weight_g,
                    stone_weight_g=it.stone_weight_g,
                    net_weight_g=it.net_weight_g,
                    purity_carat=it.purity_carat,
                    rate_per_gram=it.rate_per_gram,
                )
            loan.status = Loan.Status.CLOSED
            loan.closed_at = timezone.now()
            loan.renewed_to = new_loan
            loan.save()

        messages.success(request,
            f'Loan {loan.loan_no} renewed → new loan {new_loan.loan_no} '
            f'created with outstanding principal as new principal.')
        return _back_to_loan(new_loan.pk)

    return render(request, 'loans/action_renew.html', {
        **admin.site.each_context(request),
        **_ltv_ctx(loan),
        'loan': loan,
        'default_tenure': 12,
        'blockers': _action_blockers(loan),
        'outstanding': loan.outstanding_principal(),
        'interest_due': loan.interest_due_now(),
        'add_repayment_url': reverse('admin:loans_repayment_add')
                             + f'?loan={loan.pk}',
    })


# ---------- TOP-UP ----------

@loan_action
def topup_loan(request, loan):
    if request.method == 'POST':
        try:
            extra = Decimal(request.POST.get('extra_amount') or '0')
        except Exception:
            extra = Decimal('0')
        if extra <= 0:
            messages.error(request, 'Enter a positive top-up amount.')
            return _back_to_loan(loan.pk)

        tenure_months = int(request.POST.get('tenure_months') or 12)
        rate_pct = Decimal(request.POST.get('interest_rate_pct')
                           or str(loan.interest_rate_pct))
        rate_type = request.POST.get('rate_type') or loan.rate_type
        start_date = timezone.now().date()
        new_principal = loan.outstanding_principal().amount + extra

        blockers = _action_blockers(loan, new_principal)
        if blockers:
            for e in blockers:
                messages.error(request, e)
            return redirect(reverse('loans:topup', args=[loan.pk]))

        with transaction.atomic():
            new_loan = Loan(
                customer=loan.customer,
                principal=Money(new_principal, 'INR'),
                rate_type=rate_type,
                interest_rate_pct=rate_pct,
                tenure_months=tenure_months,
                start_date=start_date,
                maturity_date=start_date + relativedelta(months=tenure_months),
                packet_no=loan.packet_no,
                purpose=loan.purpose,
                notes=f'Top-up of ₹{extra} from {loan.loan_no} on {start_date}. '
                      f'New principal = old outstanding ₹{loan.outstanding_principal().amount} '
                      f'+ top-up ₹{extra}.',
                status=Loan.Status.ACTIVE,
            )
            new_loan.save()
            for it in loan.items.all():
                GoldItem.objects.create(
                    loan=new_loan,
                    description=it.description,
                    gross_weight_g=it.gross_weight_g,
                    stone_weight_g=it.stone_weight_g,
                    net_weight_g=it.net_weight_g,
                    purity_carat=it.purity_carat,
                    rate_per_gram=it.rate_per_gram,
                )
            loan.status = Loan.Status.CLOSED
            loan.closed_at = timezone.now()
            loan.renewed_to = new_loan
            loan.save()

        messages.success(request,
            f'Loan {loan.loan_no} topped up → new loan {new_loan.loan_no} '
            f'created with principal ₹{new_principal} '
            f'(₹{extra} extra disbursed to customer).')
        return _back_to_loan(new_loan.pk)

    return render(request, 'loans/action_topup.html', {
        **admin.site.each_context(request),
        **_ltv_ctx(loan),
        'loan': loan,
        'default_tenure': 12,
        'is_topup': True,
        'blockers': _action_blockers(loan),
        'outstanding': loan.outstanding_principal(),
        'interest_due': loan.interest_due_now(),
        'add_repayment_url': reverse('admin:loans_repayment_add')
                             + f'?loan={loan.pk}',
    })
