from django.core.management.base import BaseCommand
from apps.loans.tasks import classify_npa_all_tenants


class Command(BaseCommand):
    help = 'Run NPA classification for all tenants now (sync, no broker needed).'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD; defaults to today')

    def handle(self, *args, **opts):
        result = classify_npa_all_tenants.apply(args=[opts.get('date')]).get()
        self.stdout.write(self.style.SUCCESS(result))
