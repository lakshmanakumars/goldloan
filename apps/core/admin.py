"""Shared admin mixins.

`TenantAdminMixin` provides permission methods for tenant-scoped admin
classes. Combined with the role-based matrix in apps.core.permissions, each
ModelAdmin sets `tenant_resource` to one of the matrix keys (e.g. 'loan',
'customer', 'repayment') and inherits the right read/write gates.

Tenant data isolation itself happens at the queryset level via
`TenantAwareManager` — this mixin only controls UI visibility.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.main import ChangeList
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from unfold.admin import ModelAdmin
from apps.core.forms import TenantUniqueAdminForm
from apps.core.permissions import role_can, R, W

logger = logging.getLogger(__name__)


class _ConfigurableChangeList(ChangeList):
    """ChangeList that honours a per-request ``?per_page=N`` override so the
    page size is configurable on the fly (bounded to a sane range). The default
    comes from ``settings.ADMIN_LIST_PER_PAGE`` via the ModelAdmin.
    """

    def get_filters_params(self, params=None):
        # Don't let ?per_page leak into the filter machinery (it isn't a field).
        params = super().get_filters_params(params)
        params.pop('per_page', None)
        return params

    def get_results(self, request):
        per = request.GET.get('per_page')
        if per:
            try:
                self.list_per_page = max(5, min(int(per), 500))
            except (TypeError, ValueError):
                pass
        return super().get_results(request)


class CrmListAdminMixin:
    """Shared list-page behaviour: configurable pagination + Unfold's
    filter "Apply" button. Mix into any Unfold ModelAdmin.
    """
    list_per_page = getattr(settings, 'ADMIN_LIST_PER_PAGE', 25)
    list_filter_submit = True

    def get_changelist(self, request, **kwargs):
        return _ConfigurableChangeList



class IntegrityErrorGuardMixin:
    """Turn a stray unique-constraint IntegrityError on an admin add/change
    form into an error message instead of a 500. Mix into every ModelAdmin.
    """
    def changeform_view(self, request, object_id=None, form_url='',
                        extra_context=None):
        # Last-resort guard: form validation and the auto-number retry should
        # stop every duplicate, but if a unique constraint still fires (e.g.
        # two users saving the same record at once) show an error and keep
        # the user on the form instead of a bare "Server Error (500)". The
        # admin wraps the save in a transaction, so nothing partial is kept.
        try:
            return super().changeform_view(request, object_id, form_url,
                                           extra_context)
        except IntegrityError:
            logger.exception('IntegrityError saving %s (object_id=%s)',
                             self.model._meta.label, object_id)
            messages.error(request, (
                'This %s could not be saved because it duplicates an '
                'existing record (it may have just been saved by someone '
                'else). Nothing was saved; please check and try again.'
            ) % self.model._meta.verbose_name)
            return HttpResponseRedirect(request.get_full_path())


class TenantAdminMixin:
    # Subclasses MUST set this to one of the keys in MATRIX
    # (e.g. 'customer', 'loan', 'repayment', 'branch', 'user', 'rate').
    tenant_resource = None

    def has_module_permission(self, request):
        if not self._tenant_perm(request):
            return False
        return role_can(request.user, self.tenant_resource, R)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        if not self._tenant_perm(request):
            return False
        return role_can(request.user, self.tenant_resource, W)

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request)

    @staticmethod
    def _tenant_perm(request):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        tenant = getattr(request, 'tenant', None)
        if tenant is None or not user.is_staff:
            return False
        return user.tenant_id == tenant.id


class TenantModelAdmin(IntegrityErrorGuardMixin, CrmListAdminMixin,
                       TenantAdminMixin, ModelAdmin):
    """Convenience base class: Unfold ModelAdmin + tenant permission gates.

    Subclasses MUST set `tenant_resource` to one of the matrix keys.

    Uses `TenantUniqueAdminForm` by default so tenant-scoped uniqueness
    constraints produce friendly inline errors instead of a 500. Subclasses may
    override `form` with a subclass of it to add model-specific validation.

    Inherits configurable pagination (``?per_page=N`` + ADMIN_LIST_PER_PAGE)
    and the filter Apply button from CrmListAdminMixin.
    """
    form = TenantUniqueAdminForm

