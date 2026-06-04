"""Thread-local current tenant.

The middleware sets this at the start of each request; managers and signals
read it. For Celery, tasks must set it explicitly before doing tenant work
(see apps.notifications.tasks).
"""
import threading

_locals = threading.local()


def set_current_tenant(tenant):
    _locals.tenant = tenant


def get_current_tenant():
    return getattr(_locals, 'tenant', None)


def clear_current_tenant():
    if hasattr(_locals, 'tenant'):
        del _locals.tenant
