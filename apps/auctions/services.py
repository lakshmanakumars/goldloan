"""Auction services: eligibility detection + notice PDF generation."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from djmoney.money import Money
from weasyprint import HTML

from apps.loans.models import Loan
from .models import Auction


# How many days past maturity before we open an auction case.
NPA_TO_AUCTION_DAYS = 30


def detect_eligible_loans(tenant, today=None):
    """For a given tenant, find loans that should become auction-eligible
    and open an Auction row for each. Returns the number created.

    A loan qualifies under either of two independent triggers (an existing
    Auction row excludes it, so each loan is opened at most once):

    1. Standard NPA path: an OVERDUE loan whose maturity is at least
       NPA_TO_AUCTION_DAYS days in the past.
    2. Never-paid fast-track: an OVERDUE loan whose tenure is over (on/after
       maturity) and whose borrower has never paid interest even once.
       No extra grace beyond maturity.
    """
    today = today or timezone.localdate()
    threshold = today - timedelta(days=NPA_TO_AUCTION_DAYS)

    # 1. Standard path: overdue + matured NPA_TO_AUCTION_DAYS+ days ago.
    standard = Loan.objects.filter(
        status=Loan.Status.OVERDUE,
        maturity_date__lte=threshold,
    )

    # 2. Fast-track: overdue + tenure over + zero interest payments ever.
    #    Requires OVERDUE (not ACTIVE) so short-tenure loans that mature
    #    before the NPA classifier flips them aren't auctioned prematurely.
    never_paid = Loan.objects.filter(
        status=Loan.Status.OVERDUE,
        maturity_date__lte=today,
    ).exclude(repayments__interest_paid__gt=Decimal('0'))

    candidates = (standard | never_paid).distinct().exclude(
        auction__isnull=False)

    created = 0
    for loan in candidates:
        Auction.objects.create(
            tenant=tenant, loan=loan,
            status=Auction.Status.ELIGIBLE,
            eligible_at=timezone.now(),
        )
        created += 1
    return created


def total_dues(loan, on_date=None) -> Money:
    """Outstanding principal + interest_due_now snapshot."""
    out = loan.outstanding_principal()
    due = loan.interest_due_now()
    return Money(
        Decimal(out.amount) + Decimal(due.amount),
        'INR',
    )


def build_notice_pdf(auction: Auction, notice_no: int) -> bytes:
    """Render the auction notice PDF for the given notice number."""
    loan = auction.loan
    customer = loan.customer
    tenant = auction.tenant

    secondary = (customer.preferred_language or 'en-in')
    if secondary == 'en-in':
        secondary = None

    items = list(loan.items.all())
    dues = total_dues(loan)

    notice_text_days = 14
    if notice_no == 1:
        sub_title = 'FIRST AND FINAL NOTICE FOR AUCTION (Notice 1 of 2)'
    elif notice_no == 2:
        sub_title = 'FINAL NOTICE BEFORE AUCTION (Notice 2 of 2)'
    else:
        sub_title = 'AUCTION NOTICE'

    html_str = render_to_string('auctions/notice_pdf.html', {
        'auction': auction, 'loan': loan, 'customer': customer,
        'tenant': tenant, 'items': items, 'dues': dues,
        'notice_no': notice_no, 'sub_title': sub_title,
        'notice_text_days': notice_text_days,
        'today': timezone.localdate(),
        'secondary_lang': secondary,
    })
    return HTML(string=html_str).write_pdf()
