from django.db import models
from apps.core.tenancy import get_current_tenant


class TenantAwareManager(models.Manager):
    """Auto-filter querysets by the current tenant.

    If no tenant is set (super-admin host or shell), returns everything.
    Use `Model.all_objects` to bypass the filter explicitly.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is not None:
            return qs.filter(tenant=tenant)
        return qs


class TenantAwareModel(models.Model):
    """Base class for any model that belongs to a tenant.

    Adds a non-null FK to iam.Tenant and auto-populates it on save when a
    current tenant is set.
    """

    tenant = models.ForeignKey(
        'iam.Tenant',
        on_delete=models.CASCADE,
        related_name='+',
        editable=False,
    )

    objects = TenantAwareManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant is None:
                raise RuntimeError(
                    f'Cannot save {self.__class__.__name__} without a current '
                    'tenant. Call set_current_tenant() first or pass tenant '
                    'explicitly.'
                )
            self.tenant = tenant
        super().save(*args, **kwargs)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
