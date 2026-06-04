from django.core.management.base import BaseCommand, CommandError
from apps.iam.services import onboard_tenant, OnboardError


class Command(BaseCommand):
    help = 'Onboard a new pawn broker tenant and create their owner user.'

    def add_arguments(self, parser):
        parser.add_argument('--name', required=True,
                            help='Business name e.g. "Varaahi Gold Finance"')
        parser.add_argument('--slug', default=None,
                            help='Subdomain slug; auto-derived if omitted')
        parser.add_argument('--owner-username', required=True)
        parser.add_argument('--owner-email', required=True)
        parser.add_argument('--owner-password', required=True)
        parser.add_argument('--phone', required=True)
        parser.add_argument('--license-no', default='')
        parser.add_argument('--gst-no', default='')
        parser.add_argument('--plan', default='starter')

    def handle(self, *args, **opts):
        try:
            tenant, branch, owner = onboard_tenant(
                name=opts['name'],
                slug=opts['slug'],
                owner_username=opts['owner_username'],
                owner_email=opts['owner_email'],
                owner_password=opts['owner_password'],
                phone=opts['phone'],
                license_no=opts['license_no'],
                gst_no=opts['gst_no'],
                plan=opts['plan'],
            )
        except OnboardError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f"Onboarded tenant '{tenant.name}' (slug={tenant.slug})\n"
            f"  Login URL: {tenant.subdomain_url}admin/\n"
            f"  Owner    : {owner.username} / {opts['owner_password']}\n"
            f"  Branch   : {branch.code} (primary)"
        ))
