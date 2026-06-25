from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.loans.models import Loan


class Command(BaseCommand):
    help = (
        'Renumber existing loans to the year-scoped L-YYYY-NNNNN format. '
        'Numbers are assigned per tenant, per calendar year of start_date, '
        'in booking order (start_date, then id). Dry-run by default; pass '
        '--apply to write the changes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually write the new numbers (default is a dry run).')
        parser.add_argument(
            '--tenant', dest='tenant_slug',
            help='Limit to a single tenant slug (default: all tenants).')

    def handle(self, *args, **opts):
        apply = opts['apply']
        tenant_slug = opts.get('tenant_slug')

        qs = Loan.all_objects.all()
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)

        # Group by (tenant, year), ordered so the lowest number goes to the
        # earliest booking. id is the stable tiebreak within a single day.
        groups = defaultdict(list)
        for loan in qs.order_by('start_date', 'id'):
            groups[(loan.tenant_id, loan.start_date.year)].append(loan)

        planned = []  # (loan, old_no, new_no)
        for (tenant_id, year), loans in groups.items():
            for i, loan in enumerate(loans, start=1):
                new_no = f'L-{year}-{i:05d}'
                if new_no != loan.loan_no:
                    planned.append((loan, loan.loan_no, new_no))

        if not planned:
            self.stdout.write(self.style.SUCCESS(
                'Nothing to do — all loan numbers already match the new '
                'format.'))
            return

        for loan, old_no, new_no in planned:
            self.stdout.write(f'  {old_no:<14} -> {new_no}')
        self.stdout.write(
            f'{len(planned)} loan(s) to renumber across '
            f'{len({(l.tenant_id, n[:6]) for l, _, n in planned})} '
            f'tenant/year group(s).')

        if not apply:
            self.stdout.write(self.style.WARNING(
                'Dry run — no changes written. Re-run with --apply to commit.'))
            return

        # Two-phase update to dodge transient (tenant, loan_no) collisions:
        # stage every changing row to a unique temp value, then to its final.
        with transaction.atomic():
            changing = [loan for loan, _, _ in planned]
            for loan in changing:
                loan.loan_no = f'__TMP__{loan.id}'
            Loan.all_objects.bulk_update(changing, ['loan_no'])

            for loan, _, new_no in planned:
                loan.loan_no = new_no
            Loan.all_objects.bulk_update(changing, ['loan_no'])

        self.stdout.write(self.style.SUCCESS(
            f'Renumbered {len(planned)} loan(s).'))
