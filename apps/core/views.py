from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control

from apps.core import branding


def home(request):
    """Landing page.

    - On the super-admin host: minimal platform info + login link.
    - On a tenant subdomain: branded customer-facing landing (Vaarahi style)
      with hero + 7 benefits in EN + customer's preferred lang (defaults to
      Telugu for India), plus a "Sign in" CTA for staff.
    """
    if request.user.is_authenticated:
        return redirect('/admin/')

    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return render(request, 'platform_landing.html')
    return render(request, 'tenant_landing.html', {'tenant': tenant})


@cache_control(max_age=300)
def theme_css(request):
    """Per-tenant theme stylesheet.

    Re-themes the static ``vaarahi.css`` (via its ``--vh-*`` variables) and
    Unfold's Tailwind ``--color-primary-*`` ramp from the current tenant's
    chosen colours. On the super-admin host (no tenant) it emits the default
    Vaarahi brand, so the platform keeps its own identity.

    Loaded site-wide through the Unfold ``STYLES`` config, so it themes every
    admin page. The request carries the tenant subdomain, so the middleware
    has already resolved ``request.tenant`` by the time we get here.
    """
    tenant = getattr(request, 'tenant', None)
    primary = getattr(tenant, 'primary_color', None) or branding.DEFAULT_PRIMARY
    accent = getattr(tenant, 'accent_color', None) or branding.DEFAULT_ACCENT

    ramp = branding.palette(primary)
    primary_dark = branding.shade(primary, -0.18)
    primary_soft = branding.shade(primary, 0.92)

    unfold_vars = '\n'.join(
        f'  --color-primary-{k}: {v};' for k, v in ramp.items()
    )
    css = f""":root {{
  --vh-primary:      {primary};
  --vh-primary-dark: {primary_dark};
  --vh-primary-soft: {primary_soft};
  --vh-accent:       {accent};
{unfold_vars}
}}
"""
    return HttpResponse(css, content_type='text/css')
