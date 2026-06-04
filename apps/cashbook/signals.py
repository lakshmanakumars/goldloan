"""Auto-post cash transactions when loans are disbursed and repayments
are received. Manual cash entries (capital, drawal, expense, bank
transfers, adjustments) are entered through the admin form.
"""
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.money import Money

from apps.loans.models import Loan, Repayment
from .models import CashTransaction


@receiver(post_save, sender=Loan)
def post_disbursement(sender, instance: Loan, created, **kwargs):
    """When a new active loan is created, record cash going OUT."""
    if not created:
        return
    if instance.status not in (Loan.Status.ACTIVE, Loan.Status.OVERDUE):
        return
    # Idempotency: only one auto-row per loan
    if CashTransaction.all_objects.filter(
            source_loan=instance,
            kind=CashTransaction.Kind.DISBURSE_OUT).exists():
        return
    CashTransaction.all_objects.create(
        tenant=instance.tenant,
        branch=instance.branch,
        txn_date=instance.start_date,
        kind=CashTransaction.Kind.DISBURSE_OUT,
        amount=instance.principal,
        source_loan=instance,
        mode=CashTransaction.Mode.CASH,
        note=f'Auto: loan {instance.loan_no} disbursed to '
             f'{instance.customer.name}',
    )


@receiver(post_save, sender=Repayment)
def post_repayment(sender, instance: Repayment, created, **kwargs):
    """When a repayment is recorded, record cash coming IN."""
    if not created:
        return
    if CashTransaction.all_objects.filter(
            source_repayment=instance,
            kind=CashTransaction.Kind.REPAYMENT_IN).exists():
        return
    total = (Decimal(instance.principal_paid.amount or 0)
             + Decimal(instance.interest_paid.amount or 0))
    if total <= 0:
        return
    # Map repayment mode → cash transaction mode
    mode_map = {
        Repayment.Mode.CASH: CashTransaction.Mode.CASH,
        Repayment.Mode.UPI:  CashTransaction.Mode.UPI,
        Repayment.Mode.BANK: CashTransaction.Mode.BANK,
    }
    CashTransaction.all_objects.create(
        tenant=instance.tenant,
        branch=instance.loan.branch,
        txn_date=instance.paid_at.date(),
        kind=CashTransaction.Kind.REPAYMENT_IN,
        amount=Money(total, 'INR'),
        source_repayment=instance,
        source_loan=instance.loan,
        mode=mode_map.get(instance.mode, CashTransaction.Mode.CASH),
        note=f'Auto: repayment on loan {instance.loan.loan_no} '
             f'(P:{instance.principal_paid.amount} '
             f'I:{instance.interest_paid.amount})',
    )
