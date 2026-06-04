from .base import *  # noqa

DEBUG = True

INTERNAL_IPS = ['127.0.0.1']

# Allow any *.localhost subdomain for tenant testing
ALLOWED_HOSTS = list(ALLOWED_HOSTS) + ['*']

CSRF_TRUSTED_ORIGINS = [
    'http://*.localhost:8000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
