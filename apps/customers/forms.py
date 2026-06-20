from django import forms
from apps.core.forms import TenantUniqueAdminForm
from apps.core.tenancy import get_current_tenant
from .models import Customer


class CustomerAdminForm(TenantUniqueAdminForm):
    """Customer admin form.

    Tenant-scoped uniqueness for ``phone`` and ``code`` (both backed by
    ``UniqueConstraint``) is handled by the base ``TenantUniqueAdminForm``.
    This adds duplicate checks for ``email`` and ``name``, which have no DB
    constraint but should still be unique per tenant.
    """

    class Meta:
        model = Customer
        fields = '__all__'

    def _check_unique(self, field, label):
        value = self.cleaned_data.get(field)
        tenant = (self.instance.tenant_id and self.instance.tenant
                  or get_current_tenant())
        if tenant is None or not value:
            return value
        qs = Customer.all_objects.filter(tenant=tenant, **{field: value})
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f'A customer with this {label} already exists.')
        return value

    def clean_email(self):
        return self._check_unique('email', 'email')

    def clean_name(self):
        return self._check_unique('name', 'name')
