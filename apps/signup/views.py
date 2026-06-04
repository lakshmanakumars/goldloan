from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.iam.models import Tenant
from .forms import SignupForm, RESERVED_SLUGS
from .models import SignupRequest
from . import services


def signup_form(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            signup = form.save()
            services.send_verification_email(signup)
            return redirect(reverse('signup:sent') + f'?id={signup.id}')
    else:
        form = SignupForm()
    return render(request, 'signup/form.html', {'form': form,
                                                'title': 'Sign up'})


def signup_sent(request):
    signup_id = request.GET.get('id')
    signup = SignupRequest.objects.filter(id=signup_id).first() if signup_id else None
    return render(request, 'signup/sent.html', {'signup': signup,
                                                'title': 'Check your email'})


def verify_signup(request, token):
    signup = get_object_or_404(SignupRequest, token=token)
    if signup.is_verified:
        return render(request, 'signup/verify_success.html', {
            'signup': signup,
            'tenant': signup.tenant_created,
            'login_url': (f'http://{signup.tenant_created.slug}.'
                          f'{settings.TENANT_BASE_DOMAIN}:8765/admin/'),
            'title': 'Already verified',
            'already': True,
        })
    if signup.is_expired:
        return render(request, 'signup/verify_error.html', {
            'reason': 'expired',
            'title': 'Link expired',
        }, status=410)
    try:
        tenant, owner, password = services.finalize_signup(signup)
    except Exception as exc:
        return render(request, 'signup/verify_error.html', {
            'reason': 'error',
            'detail': str(exc),
            'title': 'Could not activate',
        }, status=500)
    return render(request, 'signup/verify_success.html', {
        'signup': signup,
        'tenant': tenant,
        'owner': owner,
        'login_url': (f'http://{tenant.slug}.{settings.TENANT_BASE_DOMAIN}'
                      f':8765/admin/'),
        'title': f'{tenant.name} is ready',
        'already': False,
    })


@require_GET
def check_slug(request):
    """JSON endpoint: ?slug=foo → {available, normalized, suggested}."""
    raw = (request.GET.get('slug') or '').strip().lower()
    norm = slugify(raw)[:31]
    if not norm:
        return JsonResponse({'available': False, 'reason': 'empty',
                             'normalized': '', 'suggested': ''})
    if norm in RESERVED_SLUGS:
        return JsonResponse({'available': False, 'reason': 'reserved',
                             'normalized': norm,
                             'suggested': f'{norm}-gold'})
    taken = Tenant.objects.filter(slug=norm).exists()
    if taken:
        # naive suggestion
        for i in range(2, 8):
            cand = f'{norm}{i}'
            if not Tenant.objects.filter(slug=cand).exists() \
                    and cand not in RESERVED_SLUGS:
                return JsonResponse({'available': False, 'reason': 'taken',
                                     'normalized': norm, 'suggested': cand})
        return JsonResponse({'available': False, 'reason': 'taken',
                             'normalized': norm, 'suggested': ''})
    return JsonResponse({'available': True, 'normalized': norm,
                         'suggested': ''})
