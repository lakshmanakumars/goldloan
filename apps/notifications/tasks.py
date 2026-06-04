"""Celery tasks for monthly interest reminders.

For each active tenant, iterate active loans, compute the monthly interest
due, create an InterestReminder row (idempotent per loan+month+channel),
and dispatch via the configured sender.
"""
import logging
from datetime import date
from celery import shared_task
from django.utils import timezone

from apps.core.tenancy import set_current_tenant, clear_current_tenant
from apps.iam.models import Tenant
from apps.loans.models import Loan
from apps.notifications.models import InterestReminder
from apps.notifications import services

log = logging.getLogger(__name__)


REMINDER_TEMPLATES = {
    'en-in': (
        "Namaste {name}, gold loan {loan_no}: Rs.{due:.2f} interest is "
        "due now ({months} month(s) at Rs.{monthly:.2f}/mo). Outstanding "
        "principal Rs.{outstanding:.2f}. Please pay to keep your pledge "
        "safe. - {tenant}"
    ),
    'te': (
        "నమస్తే {name} గారు, బంగారు రుణం {loan_no}: ఇప్పుడు రూ.{due:.2f} "
        "వడ్డీ చెల్లించాల్సి ఉంది ({months} నెల(లు), నెలవారీ "
        "రూ.{monthly:.2f}). బకాయి మూలధనం రూ.{outstanding:.2f}. మీ తాకట్టు "
        "సురక్షితంగా ఉండాలంటే దయచేసి చెల్లించండి. - {tenant}"
    ),
    'hi': (
        "नमस्ते {name}, गोल्ड लोन {loan_no}: अभी रु.{due:.2f} ब्याज "
        "देय है ({months} माह, मासिक रु.{monthly:.2f})। बकाया मूलधन "
        "रु.{outstanding:.2f}। कृपया अपनी गिरवी सुरक्षित रखने हेतु "
        "भुगतान करें। - {tenant}"
    ),
}


def _build_message(tenant, loan, interest_due=None):
    """Build the reminder body using *actual* outstanding interest dues.

    The optional `interest_due` argument is accepted for backward-compat
    with older callers; if omitted, it's computed from loan.interest_due_now().
    """
    if interest_due is None:
        interest_due = loan.interest_due_now()
    lang = getattr(loan.customer, 'preferred_language', 'en-in') or 'en-in'
    template = REMINDER_TEMPLATES.get(lang, REMINDER_TEMPLATES['en-in'])
    return template.format(
        name=loan.customer.name,
        loan_no=loan.loan_no,
        due=interest_due.amount,
        months=loan.months_charged(),
        monthly=loan.monthly_interest().amount,
        outstanding=loan.outstanding_principal().amount,
        principal=loan.principal.amount,  # still available for older templates
        tenant=tenant.name,
    )


@shared_task(bind=True, name='apps.notifications.tasks.send_monthly_interest_reminders')
def send_monthly_interest_reminders(self, period: str = None):
    """Run on the 1st of every month at 09:00 IST (configured in celery.py).

    Args:
        period: optional ISO date (YYYY-MM-DD); defaults to today's first-of-month.
    """
    if period:
        period_month = date.fromisoformat(period).replace(day=1)
    else:
        period_month = timezone.now().date().replace(day=1)

    total_sent = 0
    total_skipped = 0

    tenants = Tenant.objects.filter(
        status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE])
    for tenant in tenants:
        set_current_tenant(tenant)
        try:
            loans = Loan.objects.filter(status=Loan.Status.ACTIVE)
            for loan in loans.select_related('customer'):
                if not loan.customer.phone:
                    total_skipped += 1
                    continue
                # Use the actual current dues (accrued − paid), not just the
                # one-month figure, so the message reflects reality.
                interest = loan.interest_due_now()
                if interest.amount <= 0:
                    # Nothing owed — customer is current; skip the reminder.
                    total_skipped += 1
                    continue
                msg = _build_message(tenant, loan, interest)
                reminder, created = InterestReminder.all_objects.get_or_create(
                    tenant=tenant,
                    loan=loan,
                    period_month=period_month,
                    channel=InterestReminder.Channel.WHATSAPP,
                    defaults={
                        'interest_due': interest,
                        'to_phone': loan.customer.phone,
                        'message': msg,
                        'status': InterestReminder.Status.PENDING,
                    },
                )
                if not created and reminder.status == InterestReminder.Status.SENT:
                    total_skipped += 1
                    continue
                try:
                    services.send_whatsapp(reminder.to_phone, reminder.message)
                    reminder.status = InterestReminder.Status.SENT
                    reminder.sent_at = timezone.now()
                    reminder.error = ''
                except Exception as exc:  # pragma: no cover
                    reminder.status = InterestReminder.Status.FAILED
                    reminder.error = str(exc)
                    log.exception('Reminder send failed for %s', reminder)
                reminder.save()
                if reminder.status == InterestReminder.Status.SENT:
                    total_sent += 1

                # ---- Also send email if customer has one ----
                cust_email = (loan.customer.email or '').strip()
                if cust_email:
                    erem, ecreated = InterestReminder.all_objects.get_or_create(
                        tenant=tenant, loan=loan,
                        period_month=period_month,
                        channel=InterestReminder.Channel.EMAIL,
                        defaults={
                            'interest_due': interest,
                            'to_phone': cust_email,  # reuse column for address
                            'message': msg,
                            'status': InterestReminder.Status.PENDING,
                        },
                    )
                    if ecreated or erem.status != InterestReminder.Status.SENT:
                        text, html = services.render_email(
                            'emails/interest_reminder',
                            {'message': msg, 'tenant': tenant,
                             'interest_due': f'{interest.amount:.2f}',
                             'loan_no': loan.loan_no,
                             'period': period_month.strftime('%b %Y'),
                             'site_base_url': settings.SITE_BASE_URL})
                        result = services.send_email(
                            cust_email,
                            f'{tenant.name} — Interest due on {loan.loan_no}',
                            text, html)
                        if result.get('status') == 'sent':
                            erem.status = InterestReminder.Status.SENT
                            erem.sent_at = timezone.now()
                            erem.error = ''
                            total_sent += 1
                        else:
                            erem.status = InterestReminder.Status.FAILED
                            erem.error = result.get('error', 'unknown')
                        erem.save()
        finally:
            clear_current_tenant()

    summary = f'Reminders for {period_month}: sent={total_sent} skipped={total_skipped}'
    log.info(summary)
    return summary
