"""NPA / overdue auto-classifier.

Runs nightly via Celery Beat. For every active tenant, marks an active loan
as OVERDUE when it has missed monthly interest for more than the configured
threshold (default 30 days since last interest payment OR since loan start).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

from apps.core.tenancy import set_current_tenant, clear_current_tenant
from apps.iam.models import Tenant
from apps.loans.models import Loan

log = logging.getLogger(__name__)

OVERDUE_DAYS = 30  # config knob — interest unpaid for this many days = NPA


def _last_interest_payment_date(loan):
    last = loan.repayments.filter(
        interest_paid__gt=Decimal('0')
    ).order_by('-paid_at').first()
    return last.paid_at.date() if last else loan.start_date


def classify_one_tenant(tenant, today=None):
    today = today or timezone.now().date()
    moved, kept = 0, 0
    for loan in Loan.objects.filter(status=Loan.Status.ACTIVE):
        last_paid = _last_interest_payment_date(loan)
        days = (today - last_paid).days
        if days > OVERDUE_DAYS:
            loan.status = Loan.Status.OVERDUE
            loan.save(update_fields=['status', 'updated_at'])
            moved += 1
        else:
            kept += 1
    # Optional: also flip OVERDUE → ACTIVE if customer just paid this month.
    for loan in Loan.objects.filter(status=Loan.Status.OVERDUE):
        last_paid = _last_interest_payment_date(loan)
        days = (today - last_paid).days
        if days <= OVERDUE_DAYS:
            loan.status = Loan.Status.ACTIVE
            loan.save(update_fields=['status', 'updated_at'])
            moved += 1
    return {'moved': moved, 'kept': kept}


@shared_task(bind=True, name='apps.loans.tasks.classify_npa_all_tenants')
def classify_npa_all_tenants(self, on_date=None):
    """Iterate every active tenant and run NPA classification."""
    from datetime import date as _date
    today = _date.fromisoformat(on_date) if on_date else timezone.now().date()
    total_moved = 0
    tenants = Tenant.objects.filter(
        status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE])
    total_auctions = 0
    for tenant in tenants:
        set_current_tenant(tenant)
        try:
            r = classify_one_tenant(tenant, today=today)
            total_moved += r['moved']
            log.info('NPA %s on %s: moved=%d', tenant.slug, today, r['moved'])
            # Open auction cases for overdue loans past the auction threshold
            try:
                from apps.auctions.services import detect_eligible_loans
                created = detect_eligible_loans(tenant, today=today)
                total_auctions += created
                if created:
                    log.info('AUCTION %s on %s: opened=%d', tenant.slug, today, created)
            except Exception:
                log.exception('Auction eligibility detection failed for %s', tenant.slug)
        finally:
            clear_current_tenant()
    summary = (f'NPA classification {today}: state changes={total_moved}, '
               f'auctions opened={total_auctions}')
    log.info(summary)
    return summary
