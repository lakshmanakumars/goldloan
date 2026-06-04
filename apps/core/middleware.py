"""Resolve the current tenant from the request host and stash it in
thread-local storage so model managers can auto-filter querysets.

Subdomain rules (dev):
  admin.localhost:8000     -> super-admin   (tenant = None)
  varaahi.localhost:8000   -> tenant 'varaahi'
  localhost:8000           -> super-admin   (tenant = None)

Also activates the right UI language for the request:
    user.language  >  tenant.default_language  >  Django default
"""
from django.conf import settings
from django.http import HttpResponseNotFound
from django.utils import translation
from apps.core.tenancy import set_current_tenant, clear_current_tenant

SUPER_ADMIN_SUBDOMAINS = {'admin', 'www', ''}


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        base = settings.TENANT_BASE_DOMAIN.lower()

        subdomain = ''
        if host.endswith('.' + base):
            subdomain = host[: -(len(base) + 1)]
        elif host == base:
            subdomain = ''

        request.tenant = None
        request.is_super_admin_host = subdomain in SUPER_ADMIN_SUBDOMAINS

        if subdomain and subdomain not in SUPER_ADMIN_SUBDOMAINS:
            from apps.iam.models import Tenant
            tenant = Tenant.objects.filter(
                slug=subdomain,
                status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE],
            ).first()
            if tenant is None:
                return HttpResponseNotFound(
                    f"No active tenant '{subdomain}' on {base}."
                )
            request.tenant = tenant
            set_current_tenant(tenant)

        # Pick UI language. Priority:
        #   1. Explicit cookie set via /i18n/setlang/ (top-bar switcher)
        #   2. User's saved language preference
        #   3. Tenant's default language
        #   4. Django default (en-in)
        # Django's LocaleMiddleware already handled #1 from the cookie — we
        # only override when it's absent.
        cookie_lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if not cookie_lang:
            lang = None
            if request.user.is_authenticated:
                lang = getattr(request.user, 'language', None) or None
            if not lang and request.tenant is not None:
                lang = request.tenant.default_language or None
            if lang:
                translation.activate(lang)
                request.LANGUAGE_CODE = lang

        try:
            return self.get_response(request)
        finally:
            translation.deactivate()
            clear_current_tenant()
