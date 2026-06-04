"""Authentication backends.

TenantScopedModelBackend enforces strict subdomain isolation at login:

  - On the super-admin host (admin.localhost, bare localhost): only
    `is_superuser=True` accounts may authenticate.
  - On a tenant subdomain (e.g. lakshmidurga.localhost): only accounts
    whose `tenant_id` matches the resolved tenant may authenticate.
    Super-admins are NOT allowed to log in on tenant hosts.

Without this backend, Django's default ModelBackend would accept any
valid credentials regardless of subdomain, letting one tenant's owner
log in on another tenant's subdomain.
"""
from django.contrib.auth.backends import ModelBackend


class TenantScopedModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(
            request, username=username, password=password, **kwargs
        )
        if user is None:
            return None

        # Management commands / shell don't pass a request — allow.
        if request is None:
            return user

        tenant = getattr(request, 'tenant', None)
        is_super_host = getattr(request, 'is_super_admin_host', False)

        if is_super_host:
            return user if user.is_superuser else None

        if tenant is not None:
            if user.is_superuser:
                return None
            if user.tenant_id != tenant.id:
                return None
            return user

        return None
