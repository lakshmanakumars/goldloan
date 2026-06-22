"""Base settings shared by dev and prod."""
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('DJANGO_SECRET_KEY')
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('DJANGO_ALLOWED_HOSTS', cast=Csv())

TENANT_BASE_DOMAIN = config('TENANT_BASE_DOMAIN', default='localhost')

INSTALLED_APPS = [
    # Unfold MUST come before django.contrib.admin
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 3rd party
    'django_extensions',
    'djmoney',
    'auditlog',
    'django_celery_beat',
    'django_celery_results',
    'widget_tweaks',

    # Project apps
    'apps.core',
    'apps.iam',
    'apps.customers',
    'apps.loans',
    'apps.notifications',
    'apps.reports',
    'apps.rates',
    'apps.cashbook',
    'apps.signup',
    'apps.auctions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # LocaleMiddleware must come after SessionMiddleware and before
    # CommonMiddleware. It picks the active language from session / cookie /
    # Accept-Language header.
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Tenant resolution AFTER auth so request.user is available; activates
    # per-user / per-tenant default language too.
    'apps.core.middleware.TenantMiddleware',
    'auditlog.middleware.AuditlogMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.tenant_context',
                'apps.rates.context_processors.live_gold_rates',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_USER_MODEL = 'iam.User'

# Tenant-scoped login: see apps/iam/auth_backends.py
AUTHENTICATION_BACKENDS = [
    'apps.iam.auth_backends.TenantScopedModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-in'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True
USE_L10N = True

# Default rows-per-page on every admin list. Each list also accepts an on-the-
# fly override via the ?per_page=N query param (bounded 5..500). Change this one
# value to re-tune pagination everywhere.
ADMIN_LIST_PER_PAGE = config('ADMIN_LIST_PER_PAGE', default=25, cast=int)

# Day-first (dd-mm-yyyy) date formatting everywhere. See config/formats/en/.
FORMAT_MODULE_PATH = ['config.formats']

# Supported UI languages. Customer-facing messages additionally use
# Customer.preferred_language to render the message body.
LANGUAGES = [
    ('en-in', 'English (India)'),
    ('te', 'తెలుగు (Telugu)'),
    ('hi', 'हिन्दी (Hindi)'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/admin/'
LOGOUT_REDIRECT_URL = '/admin/login/'

# --- money ---
CURRENCIES = ('INR',)
DEFAULT_CURRENCY = 'INR'

# --- celery ---
CELERY_BROKER_URL = config('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_SERIALIZER = 'json'

# Django cache (defaults to local memory; Redis available)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'vaarahi-default',
    },
}

# --- notifications ---
NOTIFICATION_CHANNEL = config('NOTIFICATION_CHANNEL', default='log')
MSG91_AUTH_KEY = config('MSG91_AUTH_KEY', default='')
WHATSAPP_CLOUD_TOKEN = config('WHATSAPP_CLOUD_TOKEN', default='')
WHATSAPP_CLOUD_PHONE_ID = config('WHATSAPP_CLOUD_PHONE_ID', default='')

# --- email (SMTP) ---
# If EMAIL_HOST is empty, fall back to console backend (prints to stdout)
# so dev / tests work without configuring real SMTP. Set EMAIL_HOST etc.
# in .env for production (Gmail / Zoho / Outlook all work).
_email_host = config('EMAIL_HOST', default='')
EMAIL_BACKEND = ('django.core.mail.backends.smtp.EmailBackend'
                 if _email_host
                 else 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = _email_host
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL',
                            default='Vaarahi Gold Finance <noreply@vaarahi.in>')
# Used in welcome/verify emails so absolute URLs work.
SITE_BASE_URL = config('SITE_BASE_URL', default='http://localhost:8765')

# --- live gold rate ticker ---
# Which Indian city's retail rate to display in the header ticker.
# Goodreturns publishes per-city rates for these (and more):
# hyderabad, mumbai, delhi, bangalore, chennai, kolkata, pune,
# ahmedabad, jaipur, lucknow, vijayawada, visakhapatnam.
GOLDRATE_CITY = config('GOLDRATE_CITY', default='hyderabad')


# --- unfold theme (Vaarahi Gold Finance brand) ---
from django.urls import reverse_lazy
from django.templatetags.static import static
from django.utils.translation import gettext_lazy as _u


def _has_tenant(request):
    return getattr(request, 'tenant', None) is not None


def _is_superadmin_host(request):
    return (request.user.is_authenticated and request.user.is_superuser
            and getattr(request, 'tenant', None) is None)


def _can_manage_staff(request):
    if not _has_tenant(request):
        return False
    u = request.user
    return u.is_superuser or getattr(u, 'role', '') in ('owner', 'manager')


# --- white-label branding: chrome follows the current tenant, falling back
#     to the platform's own Vaarahi identity on the super-admin host.
#     Unfold 0.41 reads SITE_TITLE/SITE_HEADER once at init and the template
#     calls them with NO args, while SITE_LOGO/STYLES are called WITH request.
#     So these resolve the tenant from `request` when given, else from the
#     thread-local set by TenantMiddleware (cleared per request, no leak). ---
def _current_tenant(request=None):
    if request is not None:
        t = getattr(request, 'tenant', None)
        if t is not None:
            return t
    from apps.core.tenancy import get_current_tenant
    return get_current_tenant()


def _brand_title(request=None):
    t = _current_tenant(request)
    return t.name if t else 'Vaarahi Gold Finance'


def _brand_header(request=None):
    t = _current_tenant(request)
    return t.name if t else 'Vaarahi'


def _brand_subheader(request=None):
    t = _current_tenant(request)
    return (t.tagline or '') if t else 'Gold Finance'


def _brand_logo(request=None):
    t = _current_tenant(request)
    return t.logo.url if (t and t.logo) else None


UNFOLD = {
    'SITE_TITLE': _brand_title,
    'SITE_HEADER': _brand_header,
    'SITE_SUBHEADER': _brand_subheader,
    'SITE_LOGO': _brand_logo,
    # SITE_SYMBOL removed — the colored Material-icon box was visually heavy;
    # the sidebar now shows the per-tenant logo (if uploaded) + wordmark.
    'SHOW_HISTORY': True,
    'SHOW_VIEW_ON_SITE': False,
    'DASHBOARD_CALLBACK': 'config.dashboard.dashboard_callback',
    'STYLES': [
        lambda request: static('vaarahi/vendor/flatpickr.min.css'),
        lambda request: static('vaarahi/vaarahi.css'),
        # Per-tenant palette — MUST load after vaarahi.css so its :root
        # overrides win. Re-themes --vh-* and Unfold's --color-primary-*.
        lambda request: str(reverse_lazy('core:theme_css')),
    ],
    'SCRIPTS': [
        # flatpickr lib must load before the init script that uses it.
        lambda request: static('vaarahi/vendor/flatpickr.min.js'),
        lambda request: static('vaarahi/admin-datepicker.js'),
    ],
    'SITE_FAVICONS': [
        {'rel': 'icon', 'type': 'image/svg+xml',
         'href': lambda request: static('vaarahi/favicon.svg')},
        {'rel': 'icon', 'sizes': '32x32', 'type': 'image/png',
         'href': lambda request: static('vaarahi/favicon-32x32.png')},
        {'rel': 'icon', 'sizes': '16x16', 'type': 'image/png',
         'href': lambda request: static('vaarahi/favicon-16x16.png')},
        {'rel': 'apple-touch-icon', 'sizes': '180x180',
         'href': lambda request: static('vaarahi/favicon-180x180.png')},
    ],
    # Original orange palette (restored)
    'COLORS': {
        'primary': {
            '50':  '253 244 217',
            '100': '252 231 175',
            '200': '249 211 134',
            '300': '244 188 96',
            '400': '237 161 64',
            '500': '224 131 36',
            '600': '196 102 22',     # #c46616 — main primary
            '700': '162 77 17',
            '800': '125 57 15',
            '900': '94 42 13',
            '950': '54 24 8',
        },
    },
    'SIDEBAR': {
        'show_search': True,
        'show_all_applications': False,
        'navigation': [
            {
                'title': _u('Operations'),
                'separator': True,
                'permission': _has_tenant,
                'items': [
                    {'title': _u('Customers'), 'icon': 'group',
                     'link': reverse_lazy('admin:customers_customer_changelist')},
                    {'title': _u('Loans'), 'icon': 'account_balance_wallet',
                     'link': reverse_lazy('admin:loans_loan_changelist')},
                    {'title': _u('Repayments'), 'icon': 'payments',
                     'link': reverse_lazy('admin:loans_repayment_changelist')},
                    {'title': _u('Interest Reminders'), 'icon': 'notifications_active',
                     'link': reverse_lazy('admin:notifications_interestreminder_changelist')},
                    {'title': _u('Cash Book'), 'icon': 'savings',
                     'link': reverse_lazy('cashbook:detail')},
                    {'title': _u('Day Close'), 'icon': 'event_available',
                     'link': reverse_lazy('cashbook:day_close')},
                    {'title': _u('All Cash Transactions'), 'icon': 'receipt_long',
                     'link': reverse_lazy('admin:cashbook_cashtransaction_changelist')},
                    {'title': _u('Auctions'), 'icon': 'gavel',
                     'link': reverse_lazy('admin:auctions_auction_changelist')},
                ],
            },
            {
                'title': _u('Catalog'),
                'separator': True,
                'permission': _has_tenant,
                'items': [
                    {'title': _u('Gold Rates'), 'icon': 'monitoring',
                     'link': reverse_lazy('admin:rates_goldrate_changelist')},
                    {'title': _u('Branches'), 'icon': 'store',
                     'link': reverse_lazy('admin:iam_branch_changelist')},
                ],
            },
            {
                'title': _u('Reports'),
                'separator': True,
                'permission': _has_tenant,
                'items': [
                    {'title': _u('Daily Cash Book'), 'icon': 'today',
                     'link': reverse_lazy('reports:daily_cash_book')},
                    {'title': _u('Monthly Summary'), 'icon': 'calendar_month',
                     'link': reverse_lazy('reports:monthly_cash_summary')},
                    {'title': _u('Outstanding Portfolio'), 'icon': 'account_balance',
                     'link': reverse_lazy('reports:outstanding_portfolio')},
                    {'title': _u('Interest Earned'), 'icon': 'trending_up',
                     'link': reverse_lazy('reports:interest_earned')},
                    {'title': _u('Loan-book Networth'), 'icon': 'savings',
                     'link': reverse_lazy('reports:networth')},
                ],
            },
            {
                'title': _u('Staff & Settings'),
                'separator': True,
                'permission': _can_manage_staff,
                'items': [
                    {'title': _u('Staff (Users)'), 'icon': 'badge',
                     'link': reverse_lazy('admin:iam_user_changelist')},
                    {'title': _u('My Business'), 'icon': 'business',
                     'link': reverse_lazy('admin:iam_tenant_changelist')},
                ],
            },
            {
                'title': _u('Platform'),
                'separator': True,
                'permission': _is_superadmin_host,
                'items': [
                    {'title': _u('Pawn Brokers'), 'icon': 'storefront',
                     'link': reverse_lazy('admin:iam_tenant_changelist')},
                    {'title': _u('All Users'), 'icon': 'manage_accounts',
                     'link': reverse_lazy('admin:iam_user_changelist')},
                    {'title': _u('Broker Snapshot'), 'icon': 'leaderboard',
                     'link': reverse_lazy('reports:broker_snapshot')},
                    {'title': _u('Platform Exposure'), 'icon': 'public',
                     'link': reverse_lazy('reports:platform_exposure')},
                ],
            },
            {
                'title': _u('Audit'),
                'separator': True,
                'collapsible': True,
                'permission': lambda req: req.user.is_authenticated and req.user.is_staff,
                'items': [
                    {'title': _u('Activity Log'), 'icon': 'history',
                     'link': reverse_lazy('admin:auditlog_logentry_changelist')},
                ],
            },
        ],
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
