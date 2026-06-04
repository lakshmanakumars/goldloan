"""Auction lifecycle actions: separate URL endpoints with GET form,
POST mutation pattern — mirrors apps.loans.actions."""
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from djmoney.money import Money

from apps.core.permissions import role_can, W, R
from apps.loans.models import Loan
from apps.notifications.services import send_email, render_email
from .models import Auction, AuctionNotice
from .services import build_notice_pdf, total_dues


def _allowed(request, auction, mode=W):
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant is None or not request.user.is_staff:
        return False
    if auction.tenant_id != tenant.id or request.user.tenant_id != tenant.id:
        return False
    return role_can(request.user, 'auction', mode)


def auction_action(view):
    @wraps(view)
    @staff_member_required
    def wrapper(request, pk, *args, **kwargs):
        auction = get_object_or_404(Auction.all_objects, pk=pk)
        if not _allowed(request, auction):
            return HttpResponseForbidden('Not allowed.')
        return view(request, auction, *args, **kwargs)
    return wrapper


def _back_to(auction):
    return redirect(reverse('auctions:detail', args=[auction.pk]))


def _send_notice(auction: Auction, notice_no: int, sent_by):
    """Generate PDF, email it, log AuctionNotice. Returns the notice."""
    pdf_bytes = build_notice_pdf(auction, notice_no)
    fname = f'notice-{auction.loan.loan_no}-{notice_no}.pdf'

    notice = AuctionNotice.objects.create(
        tenant=auction.tenant, auction=auction, notice_no=notice_no,
        sent_at=timezone.now(), sent_by=sent_by,
    )
    notice.pdf_path.save(fname, ContentFile(pdf_bytes), save=True)

    channels = []
    delivery_ref = ''

    # 1. Email customer if they have one
    cust_email = (auction.loan.customer.email or '').strip()
    if cust_email:
        text, html = render_email('emails/auction_notice', {
            'notice_no': notice_no, 'auction': auction,
            'loan': auction.loan, 'customer': auction.loan.customer,
            'tenant': auction.tenant,
            'dues': total_dues(auction.loan),
            'site_base_url': settings.SITE_BASE_URL,
        })
        res = send_email(
            cust_email,
            f'AUCTION NOTICE {notice_no}/2 — Loan {auction.loan.loan_no} — {auction.tenant.name}',
            text, html,
            attachments=[(fname, pdf_bytes, 'application/pdf')],
        )
        if res.get('status') == 'sent':
            channels.append('email')

    notice.channels = channels
    notice.delivery_ref = delivery_ref
    notice.save(update_fields=['channels', 'delivery_ref'])
    return notice


# ---------- Send Notice 1 ----------

@auction_action
def send_notice_1(request, auction: Auction):
    if not auction.can_send_notice_1:
        messages.warning(request,
            f'Notice 1 cannot be sent now (status: {auction.get_status_display()}).')
        return _back_to(auction)
    if request.method == 'POST':
        with transaction.atomic():
            _send_notice(auction, 1, sent_by=request.user)
            auction.status = Auction.Status.NOTICE1_SENT
            auction.notice1_sent_at = timezone.now()
            auction.save()
        messages.success(request,
            f'Notice 1 sent for {auction.loan.loan_no}. Wait 14 days before sending Notice 2.')
        return _back_to(auction)
    return render(request, 'auctions/notice_confirm.html', {
        'auction': auction, 'notice_no': 1,
        'title': f'Send Notice 1 — {auction.loan.loan_no}',
    })


# ---------- Send Notice 2 ----------

@auction_action
def send_notice_2(request, auction: Auction):
    if not auction.can_send_notice_2:
        days_left = 14 - (timezone.now() - auction.notice1_sent_at).days \
                    if auction.notice1_sent_at else 14
        messages.warning(request,
            f'Notice 2 not yet allowed. {days_left} more day(s) required '
            f'after Notice 1.')
        return _back_to(auction)
    if request.method == 'POST':
        with transaction.atomic():
            _send_notice(auction, 2, sent_by=request.user)
            auction.status = Auction.Status.NOTICE2_SENT
            auction.notice2_sent_at = timezone.now()
            auction.save()
        messages.success(request,
            f'Notice 2 sent for {auction.loan.loan_no}. Auction can be '
            f'scheduled in 14 days.')
        return _back_to(auction)
    return render(request, 'auctions/notice_confirm.html', {
        'auction': auction, 'notice_no': 2,
        'title': f'Send Notice 2 — {auction.loan.loan_no}',
    })


# ---------- Schedule auction ----------

@auction_action
def schedule_auction(request, auction: Auction):
    if not auction.can_schedule:
        days_left = 14 - (timezone.now() - auction.notice2_sent_at).days \
                    if auction.notice2_sent_at else 14
        messages.warning(request,
            f'Auction not yet schedulable. {days_left} more day(s) required '
            f'after Notice 2.')
        return _back_to(auction)
    if request.method == 'POST':
        when_str = request.POST.get('scheduled_at', '').strip()
        location = request.POST.get('location', '').strip()
        try:
            from datetime import datetime
            when = datetime.fromisoformat(when_str)
            if timezone.is_naive(when):
                when = timezone.make_aware(when)
        except Exception:
            messages.error(request, 'Invalid date/time.')
            return _back_to(auction)
        with transaction.atomic():
            auction.scheduled_at = when
            auction.location = location
            auction.status = Auction.Status.SCHEDULED
            auction.save()
        messages.success(request,
            f'Auction scheduled for {when.strftime("%d %b %Y %H:%M")} at {location}.')
        return _back_to(auction)
    return render(request, 'auctions/schedule_form.html', {
        'auction': auction,
        'title': f'Schedule auction — {auction.loan.loan_no}',
        'tenant_name': auction.tenant.name,
    })


# ---------- Record sale ----------

@auction_action
def record_sale(request, auction: Auction):
    if not auction.can_record_sale:
        messages.warning(request,
            'Sale can only be recorded for SCHEDULED auctions.')
        return _back_to(auction)
    if request.method == 'POST':
        try:
            sold = Decimal(request.POST.get('sold_amount') or '0')
        except Exception:
            sold = Decimal('0')
        if sold <= 0:
            messages.error(request, 'Enter a positive sold amount.')
            return _back_to(auction)
        bidder_name = request.POST.get('bidder_name', '').strip()
        bidder_phone = request.POST.get('bidder_phone', '').strip()
        bidder_id_proof = request.POST.get('bidder_id_proof', '').strip()

        with transaction.atomic():
            dues = total_dues(auction.loan)
            dues_amt = Decimal(dues.amount)
            surplus = max(sold - dues_amt, Decimal('0'))
            shortfall = max(dues_amt - sold, Decimal('0'))

            auction.sold_amount = Money(sold, 'INR')
            auction.total_dues_at_sale = dues
            auction.surplus_amount = Money(surplus, 'INR')
            auction.shortfall_amount = Money(shortfall, 'INR')
            auction.bidder_name = bidder_name
            auction.bidder_phone = bidder_phone
            auction.bidder_id_proof = bidder_id_proof
            auction.status = Auction.Status.SOLD
            auction.save()
        messages.success(request,
            f'Sale recorded: ₹{sold:,.2f} → surplus ₹{surplus:,.2f}, '
            f'shortfall ₹{shortfall:,.2f}. Click "Post settlement" to '
            f'close the loan.')
        return _back_to(auction)
    return render(request, 'auctions/sale_form.html', {
        'auction': auction,
        'dues': total_dues(auction.loan),
        'title': f'Record sale — {auction.loan.loan_no}',
    })


# ---------- Post settlement ----------

@auction_action
def post_settlement(request, auction: Auction):
    if not auction.can_post_settlement:
        messages.warning(request,
            'Settlement can only be posted for SOLD auctions.')
        return _back_to(auction)
    if request.method == 'POST':
        from apps.cashbook.models import CashTransaction
        with transaction.atomic():
            # If surplus, post a cash drawal-out (refund to borrower)
            if auction.surplus_amount and auction.surplus_amount.amount > 0:
                CashTransaction.objects.create(
                    tenant=auction.tenant,
                    branch=auction.loan.branch,
                    txn_date=timezone.localdate(),
                    kind=CashTransaction.Kind.DRAWAL_OUT,
                    amount=auction.surplus_amount,
                    source_loan=auction.loan,
                    mode=CashTransaction.Mode.CASH,
                    note=(f'Auction surplus refunded to '
                          f'{auction.loan.customer.name} for '
                          f'loan {auction.loan.loan_no}'),
                    created_by=request.user,
                )
                auction.surplus_refunded_at = timezone.now()
            # Close the loan as auctioned
            auction.loan.status = Loan.Status.AUCTIONED
            auction.loan.closed_at = timezone.now()
            auction.loan.save()
            auction.status = Auction.Status.POSTED
            auction.save()
        messages.success(request,
            f'Settlement posted. Loan {auction.loan.loan_no} marked AUCTIONED.')
        return _back_to(auction)
    return render(request, 'auctions/post_confirm.html', {
        'auction': auction,
        'title': f'Post settlement — {auction.loan.loan_no}',
    })


# ---------- Cancel auction (borrower settled) ----------

@auction_action
def cancel_auction(request, auction: Auction):
    if not auction.is_open:
        messages.warning(request, 'Auction already closed.')
        return _back_to(auction)
    if request.method == 'POST':
        with transaction.atomic():
            auction.status = Auction.Status.CANCELLED
            auction.notes = (auction.notes or '') + \
                f'\nCancelled on {timezone.localdate()} by {request.user}'
            auction.save()
        messages.success(request, 'Auction cancelled.')
        return _back_to(auction)
    return render(request, 'auctions/cancel_confirm.html', {
        'auction': auction,
        'title': f'Cancel auction — {auction.loan.loan_no}',
    })
