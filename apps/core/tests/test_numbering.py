"""Regression tests for auto-generated document numbers.

Every generated number (loan no, receipt no, customer code) must stay unique
no matter how existing rows were deleted, back-dated or hand-numbered, and a
collision must advance to the next free number instead of a 500.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone
from djmoney.money import Money

from apps.core.numbering import next_number, save_with_auto_number
from apps.customers.models import Customer
from apps.iam.models import Tenant
from apps.loans.models import Loan, Repayment

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(
        name='Test Finance', slug='testfin', contact_name='T',
        contact_email='t@example.com', contact_phone='9000000000')


@pytest.fixture
def other_tenant():
    return Tenant.objects.create(
        name='Other Finance', slug='otherfin', contact_name='O',
        contact_email='o@example.com', contact_phone='9000000001')


def _customer(tenant, phone='9111111111', **kw):
    return Customer.all_objects.create(tenant=tenant, name='Cust',
                                       phone=phone, **kw)


def _loan(tenant, customer, **kw):
    return Loan.all_objects.create(
        tenant=tenant, customer=customer, principal=Money(10000, 'INR'),
        interest_rate_pct=Decimal('24'), **kw)


def _repay(loan, **kw):
    return Repayment.all_objects.create(
        tenant=loan.tenant, loan=loan,
        principal_paid=Money(100, 'INR'), **kw)


# ---------- next_number ----------

def test_next_number_uses_max_and_ignores_non_numeric(tenant):
    _customer(tenant, '9100000001', code='C-00007')
    _customer(tenant, '9100000002', code='C-OLD1')
    _customer(tenant, '9100000003', code='X-00099')
    qs = Customer.all_objects.filter(tenant=tenant)
    assert next_number(qs, 'code', 'C-', 5) == 'C-00008'


def test_next_number_rejects_unsafe_prefix(tenant):
    with pytest.raises(ValueError):
        next_number(Customer.all_objects.all(), 'code', 'C.*', 5)


# ---------- receipts ----------

def test_receipt_after_backdated_receipt_does_not_collide(tenant):
    """The Nov-2026 bug: a receipt numbered for today but back-dated."""
    loan = _loan(tenant, _customer(tenant))
    first = _repay(loan)
    today = timezone.localdate()
    assert first.receipt_no == f'RCP-{today:%Y%m%d}-001'
    first.paid_at = timezone.now() - timedelta(days=29)
    first.save()

    second = _repay(loan)
    assert second.receipt_no == f'RCP-{today:%Y%m%d}-002'


def test_receipt_after_deleted_receipt_does_not_collide(tenant):
    loan = _loan(tenant, _customer(tenant))
    _repay(loan)
    middle = _repay(loan)
    _repay(loan)
    middle.delete()
    assert _repay(loan).receipt_no.endswith('-004')


def test_receipt_numbers_are_per_tenant(tenant, other_tenant):
    a = _repay(_loan(tenant, _customer(tenant)))
    b = _repay(_loan(other_tenant, _customer(other_tenant)))
    assert a.receipt_no == b.receipt_no  # same day, independent counters


# ---------- loans ----------

def test_loan_no_after_deleted_loan_does_not_collide(tenant):
    c = _customer(tenant)
    _loan(tenant, c)
    second = _loan(tenant, c)
    third = _loan(tenant, c)
    second.delete()
    assert _loan(tenant, c).loan_no[-5:] == f'{int(third.loan_no[-5:]) + 1:05d}'


# ---------- customers ----------

def test_customer_code_skips_hand_entered_future_code(tenant):
    """last-id+1 would collide with this forever; max+1 must not."""
    first = _customer(tenant, '9200000001')
    # Hand-enter the code the old generator would predict for the 3rd row
    # (its own id + 1), so old code collided on every retry.
    manual = _customer(tenant, '9200000002', code='C-TMP')
    manual.code = f'C-{manual.id + 1:05d}'
    manual.save()
    third = _customer(tenant, '9200000003')
    assert third.code == f'C-{manual.id + 2:05d}'
    assert first.code != third.code


# ---------- retry behaviour ----------

def test_retry_advances_when_number_taken_concurrently(tenant, monkeypatch):
    """Simulate a concurrent insert grabbing the number after generation."""
    loan = _loan(tenant, _customer(tenant))
    _repay(loan)  # -001
    rp = Repayment(tenant=tenant, loan=loan,
                   principal_paid=Money(100, 'INR'))
    rp.paid_at = timezone.now()
    calls = []
    real = Repayment._next_receipt_no

    def stale_first(self):
        calls.append(1)
        if len(calls) == 1:
            return real(self)[:-3] + '001'  # stale: already taken
        return real(self)

    monkeypatch.setattr(Repayment, '_next_receipt_no', stale_first)
    rp.save()
    assert rp.receipt_no.endswith('-002')
    assert len(calls) == 2


def test_other_integrity_errors_are_not_retried(tenant):
    """A duplicate phone isn't fixable by renumbering: raise at once."""
    _customer(tenant, '9300000001')
    with pytest.raises(IntegrityError):
        _customer(tenant, '9300000001')


def test_save_with_auto_number_gives_up_after_max_retries(tenant):
    _customer(tenant, '9400000001', code='C-00001')
    c = Customer(tenant=tenant, name='X', phone='9400000002')
    with pytest.raises(IntegrityError):
        save_with_auto_number(
            c, 'code', lambda: 'C-00001',
            lambda: super(Customer, c).save(),
            taken_qs=Customer.all_objects.filter(tenant=tenant))
