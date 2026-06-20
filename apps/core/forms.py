"""Shared admin form helpers.

`TenantUniqueAdminForm` closes a class of HTTP 500 bugs in the admin: every
tenant-scoped ``UniqueConstraint`` (e.g. ``fields=['tenant', 'code']``)
references the ``tenant`` field, which is ``editable=False`` (set automatically
in ``TenantAwareModel.save``) and therefore excluded from admin forms. Django's
``Model.validate_unique`` skips any constraint that touches an excluded field,
so a duplicate is never caught at the form layer — it reaches the database and
raises an ``IntegrityError`` that surfaces as a bare "Server Error (500)".

This base form re-implements that uniqueness check against the current tenant
and reports a friendly inline error instead, for any model whose constraints
follow the ``['tenant', ...]`` pattern. Wiring it as the default form on
``TenantModelAdmin`` makes every tenant admin benefit automatically.
"""
from django import forms
from django.db.models import UniqueConstraint
from apps.core.tenancy import get_current_tenant


def _swap_date_hook(widget):
    """Replace Django's ``vDateField`` JS hook with ``flatpickr-date``.

    ``DateTimeShortcuts.js`` (and Unfold's enhancement of it) binds its
    step-one-month-at-a-time calendar to every ``input.vDateField``. Renaming
    the hook stops that binding so flatpickr — which gives a month dropdown and
    a typeable year — is the only picker. Recurses into MultiWidget subwidgets
    (split date/time) and leaves ``vTimeField`` untouched.
    """
    subs = getattr(widget, 'widgets', None)
    if subs:
        for sub in subs:
            _swap_date_hook(sub)
        return
    cls = widget.attrs.get('class', '')
    if 'vDateField' in cls:
        widget.attrs['class'] = cls.replace('vDateField', 'flatpickr-date')


class TenantUniqueAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            _swap_date_hook(field.widget)

    def _resolve_tenant(self, cleaned):
        # tenant may come from the form (rare), the bound instance, or the
        # thread-local set by TenantMiddleware for the current request.
        if cleaned.get('tenant'):
            return cleaned['tenant']
        if self.instance.tenant_id:
            return self.instance.tenant
        return get_current_tenant()

    def clean(self):
        cleaned = super().clean()
        self._validate_tenant_unique(cleaned)
        return cleaned

    def _validate_tenant_unique(self, cleaned):
        model = self._meta.model
        tenant = self._resolve_tenant(cleaned)
        if tenant is None:
            return
        for con in getattr(model._meta, 'constraints', []):
            if not isinstance(con, UniqueConstraint) or 'tenant' not in con.fields:
                continue
            scope = [f for f in con.fields if f != 'tenant']
            # Only validate when every scope field is present in this form and
            # filled — auto-generated fields excluded from the form (e.g. a
            # readonly `loan_no`) are left to the DB constraint as a backstop.
            if not scope or not all(f in cleaned for f in scope):
                continue
            if any(cleaned.get(f) in (None, '') for f in scope):
                continue
            lookup = {f: cleaned[f] for f in scope}
            qs = model._base_manager.filter(tenant=tenant, **lookup)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if not qs.exists():
                continue
            labels = ' and '.join(
                str(model._meta.get_field(f).verbose_name) for f in scope)
            msg = (f'A {model._meta.verbose_name} with this {labels} '
                   'already exists.')
            if len(scope) == 1:
                self.add_error(scope[0], msg)
            else:
                # Multi-field constraint: attach as a non-field (top-of-form)
                # error since no single field is at fault.
                self.add_error(None, msg)
