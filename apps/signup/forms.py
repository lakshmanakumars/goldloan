import re

from django import forms
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.iam.models import Tenant, User
from .models import SignupRequest


RESERVED_SLUGS = {
    'admin', 'api', 'www', 'mail', 'support', 'help', 'static', 'media',
    'app', 'apps', 'signup', 'login', 'logout', 'account', 'accounts',
    'dashboard', 'platform', 'system', 'root', 'vaarahi', 'super',
    'superadmin',
}


class SignupForm(forms.ModelForm):

    class Meta:
        model = SignupRequest
        fields = ['business_name', 'slug', 'owner_username', 'owner_email',
                  'owner_phone', 'license_no', 'gst_no']

    def clean_business_name(self):
        v = (self.cleaned_data.get('business_name') or '').strip()
        if len(v) < 3:
            raise forms.ValidationError(_('Business name is too short.'))
        return v

    def clean_slug(self):
        v = (self.cleaned_data.get('slug') or '').strip().lower()
        if not v:
            v = slugify(self.cleaned_data.get('business_name', ''))
        if not re.fullmatch(r'[a-z][a-z0-9-]{2,30}', v):
            raise forms.ValidationError(
                _('Subdomain must be 3–31 chars, lowercase letters, digits, '
                  'or hyphens; must start with a letter.'))
        if v in RESERVED_SLUGS:
            raise forms.ValidationError(_('This name is reserved.'))
        if Tenant.objects.filter(slug=v).exists():
            raise forms.ValidationError(_('This subdomain is already taken.'))
        return v

    def clean_owner_username(self):
        v = (self.cleaned_data.get('owner_username') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,30}', v):
            raise forms.ValidationError(
                _('Username must be 3–30 chars (letters, digits, _ . -).'))
        if User.objects.filter(username=v).exists():
            raise forms.ValidationError(_('This username is already taken.'))
        return v

    def clean_owner_email(self):
        v = (self.cleaned_data.get('owner_email') or '').strip().lower()
        if User.objects.filter(email=v).exists():
            raise forms.ValidationError(_('This email is already registered.'))
        return v
