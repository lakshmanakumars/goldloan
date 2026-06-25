from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.loans.models import Loan, Repayment


@receiver(post_save, sender=Repayment)
def autoclose_loan(sender, instance, **kwargs):
    """Close a loan automatically once principal + interest are fully settled.

    Fires after any repayment is saved (the row is already persisted, so the
    loan's aggregates include it). Interest-due nets off any waiver, so a
    paid+waived combination that clears the balance also triggers the close.

    Close-only: it never reopens a loan, so it won't clobber a manual
    pre-close or a renew/top-up close. Deleting a settling repayment will not
    auto-reopen — reopen manually via the loan's edit form if needed.
    """
    loan = instance.loan
    if loan.status not in (Loan.Status.ACTIVE, Loan.Status.OVERDUE):
        return
    if (loan.outstanding_principal().amount <= 0
            and loan.interest_due_now().amount <= 0):
        loan.status = Loan.Status.CLOSED
        loan.closed_at = timezone.now()
        loan.save(update_fields=['status', 'closed_at', 'updated_at'])
