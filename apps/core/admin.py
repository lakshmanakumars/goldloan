"""Shared admin mixins.

`TenantAdminMixin` provides permission methods for tenant-scoped admin
classes. Combined with the role-based matrix in apps.core.permissions, each
ModelAdmin sets `tenant_resource` to one of the matrix keys (e.g. 'loan',
'customer', 'repayment') and inherits the right read/write gates.

Tenant data isolation itself happens at the queryset level via
`TenantAwareManager` — this mixin only controls UI visibility.
"""
from django.conf import settings
from django.contrib.admin.views.main import ChangeList
from unfold.admin import ModelAdmin
from apps.core.forms import TenantUniqueAdminForm
from apps.core.permissions import role_can, R, W


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


class TenantModelAdmin(CrmListAdminMixin, TenantAdminMixin, ModelAdmin):
    """Convenience base class: Unfold ModelAdmin + tenant permission gates.

    Subclasses MUST set `tenant_resource` to one of the matrix keys.

    Uses `TenantUniqueAdminForm` by default so tenant-scoped uniqueness
    constraints produce friendly inline errors instead of a 500. Subclasses may
    override `form` with a subclass of it to add model-specific validation.

    Inherits configurable pagination (``?per_page=N`` + ADMIN_LIST_PER_PAGE)
    and the filter Apply button from CrmListAdminMixin.
    """
    form = TenantUniqueAdminForm
