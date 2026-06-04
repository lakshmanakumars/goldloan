from decouple import config, Csv
from .base import *  # noqa

DEBUG = False

# Needed for admin login over HTTPS behind a reverse proxy with tenant
# subdomains, e.g. CSRF_TRUSTED_ORIGINS=https://*.<ip>.sslip.io
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
