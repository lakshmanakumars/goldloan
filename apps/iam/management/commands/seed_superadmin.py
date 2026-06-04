from django.core.management.base import BaseCommand
from apps.iam.models import User


class Command(BaseCommand):
    help = 'Create the platform super-admin user idempotently.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin')
        parser.add_argument('--email', default='admin@goldloan.local')
        parser.add_argument('--password', default='Admin@2026!')

    def handle(self, *args, **opts):
        username = opts['username']
        u, created = User.objects.get_or_create(
            username=username,
            defaults={'email': opts['email']},
        )
        u.email = opts['email']
        u.is_staff = True
        u.is_superuser = True
        u.is_active = True
        u.tenant = None
        u.set_password(opts['password'])
        u.save()
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} super-admin '{username}' "
            f"(password: {opts['password']})"
        ))
