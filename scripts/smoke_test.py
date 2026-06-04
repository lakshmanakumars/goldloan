"""End-to-end smoke test: seed sample customer+loan in the varaahi tenant,
run the monthly reminder task synchronously, print the resulting InterestReminder.

Run from project root:
    .venv/bin/python manage.py shell < scripts/smoke_test.py
"""
from decimal import Decimal
from datetime import date

from djmoney.money import Money

from apps.core.tenancy import set_current_tenant, clear_current_tenant
from apps.iam.models import Tenant
from apps.customers.models import Customer
from apps.loans.models import Loan
from apps.notifications.models import InterestReminder
from apps.notifications.tasks import send_monthly_interest_reminders

print('=== Smoke test: varaahi tenant gold loan + monthly reminder ===')

tenant = Tenant.objects.get(slug='varaahi')
print(f'Tenant: {tenant}  status={tenant.status}')

set_current_tenant(tenant)
try:
    customer, created = Customer.objects.get_or_create(
        phone='9876500001',
        defaults={'name': 'Ravi Kumar', 'gender': 'M', 'city': 'Mumbai'},
    )
    print(f'Customer: {customer.code} {customer.name} ({"new" if created else "existing"})')

    loan, created = Loan.objects.get_or_create(
        customer=customer,
        principal=Money(50000, 'INR'),
        defaults={
            'interest_rate_pct': Decimal('24.000'),
            'tenure_months': 12,
            'start_date': date.today(),
        },
    )
    print(f'Loan: {loan.loan_no}  principal={loan.principal}  rate={loan.interest_rate_pct}% p.a.')
    print(f'  Monthly interest = {loan.monthly_interest()}')
    print(f'  Maturity date    = {loan.maturity_date}')
finally:
    clear_current_tenant()

print('\n--- Running monthly reminder task synchronously ---')
result = send_monthly_interest_reminders.apply().get()
print(f'Task result: {result}')

print('\n--- All reminders in DB ---')
for r in InterestReminder.all_objects.all().order_by('-created_at'):
    print(f'  [{r.status}] {r.loan.loan_no} {r.period_month:%Y-%m} '
          f'via {r.channel} -> {r.to_phone}')
    print(f'    msg: {r.message[:120]}')

print('\nSmoke test complete.')
