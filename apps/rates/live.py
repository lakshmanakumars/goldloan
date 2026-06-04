"""Live gold rate fetcher (India retail rates).

Priority of sources:

  1. **GoodReturns** (https://www.goodreturns.in/gold-rates/<city>.html)
     City-specific Indian retail rates for 24K / 22K / 18K per gram —
     this is what jewellers and pawn brokers across India actually quote.
     We scrape the lead-paragraph sentence which has all three rates in a
     stable format.

  2. **gold-api.com + open.er-api.com** (fallback)
     International spot (USD/oz) × USD→INR ÷ 31.1035 — only used if
     GoodReturns scraping fails (HTML change, network block, etc.).
     Will be lower than retail Indian price because it excludes Indian
     import duty + GST + jeweller markup.

  3. **Latest GoldRate row in the DB** (final fallback)
     The manually-entered rate from Catalog → Gold Rates if the broker
     keeps it up to date.

Cached 15 min in Django cache. A Celery beat task refreshes proactively.

Default city is 'hyderabad'; override per deployment via the
``GOLDRATE_CITY`` setting (or env var).
"""
import logging
import re
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)

CACHE_KEY = 'vaarahi:live_gold_rates_v2'
CACHE_TTL = 60 * 15        # 15 minutes
HTTP_TIMEOUT = 8           # seconds

GRAMS_PER_OZ = Decimal('31.1034768')

# Purity ratios (used only by the international-spot fallback)
PURITY = {
    24: Decimal('1.0000'),
    22: Decimal('0.9167'),
    18: Decimal('0.7500'),
}

# Goodreturns lead-paragraph regex — captures 24K, 22K, 18K /gram numbers
# from the wording "Today's gold price in <City> stands at ₹X per gram
# for 24 karat... ₹Y per gram for 22 karat... ₹Z per gram for 18 karat".
GOODRETURNS_RE = re.compile(
    r'&#x20b9;([\d,]+)\s*</strong>\s*per gram for 24 karat'
    r'.*?&#x20b9;([\d,]+)\s*</strong>\s*per gram for 22 karat'
    r'.*?&#x20b9;([\d,]+)\s*</strong>\s*per gram for 18 karat',
    re.S | re.I,
)

SUPPORTED_CITIES = (
    'hyderabad', 'mumbai', 'delhi', 'bangalore', 'chennai',
    'kolkata', 'pune', 'ahmedabad', 'jaipur', 'lucknow',
    'kerala', 'vijayawada', 'visakhapatnam',
)


def _get_city():
    return getattr(settings, 'GOLDRATE_CITY', 'hyderabad').lower()


def get_live_rates(force_refresh=False):
    """Return cached or freshly-fetched gold rates.

    Returns dict::

        {
          'rates': {24: Decimal, 22: Decimal, 18: Decimal},   # INR/gram
          'source': str,             # 'goodreturns.in/<city>' etc
          'city': str | None,
          'fetched_at': datetime,
          'usd_per_oz': Decimal | None,
          'usd_inr':    Decimal | None,
          'stale':      bool,
        }

    or ``None`` if all sources fail.
    """
    if not force_refresh:
        cached = cache.get(CACHE_KEY)
        if cached:
            return cached

    for fetch in (_fetch_from_goodreturns, _fetch_from_spot_apis):
        try:
            data = fetch()
            if data:
                cache.set(CACHE_KEY, data, CACHE_TTL)
                return data
        except Exception:
            log.exception('Source %s failed', fetch.__name__)

    fallback = _fetch_from_db()
    if fallback:
        cache.set(CACHE_KEY, fallback, 60 * 2)
    return fallback


def _fetch_from_goodreturns():
    """Scrape city-specific Indian retail rates from goodreturns.in."""
    city = _get_city()
    url = f'https://www.goodreturns.in/gold-rates/{city}.html'
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                      'Chrome/120 Safari/537.36',
        'Accept-Language': 'en-IN,en;q=0.9',
    })
    r.raise_for_status()
    m = GOODRETURNS_RE.search(r.text)
    if not m:
        log.warning('goodreturns: regex did not match for city=%s', city)
        return None
    k24 = Decimal(m.group(1).replace(',', ''))
    k22 = Decimal(m.group(2).replace(',', ''))
    k18 = Decimal(m.group(3).replace(',', ''))
    return {
        'rates': {24: k24, 22: k22, 18: k18},
        'source': f'goodreturns.in/{city}',
        'city': city.title(),
        'fetched_at': timezone.now(),
        'usd_per_oz': None,
        'usd_inr':    None,
        'stale': False,
    }


def _fetch_from_spot_apis():
    """Fallback: international spot via gold-api.com + USD→INR conversion."""
    try:
        r = requests.get('https://api.gold-api.com/price/XAU',
                         timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        usd_per_oz = Decimal(str(r.json().get('price') or 0))

        r = requests.get('https://open.er-api.com/v6/latest/USD',
                         timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        usd_inr = Decimal(str(r.json()['rates']['INR']))
    except Exception as exc:
        log.warning('spot APIs failed: %s', exc)
        return None

    if usd_per_oz <= 0 or usd_inr <= 0:
        return None

    inr_per_gram_24k_spot = usd_per_oz * usd_inr / GRAMS_PER_OZ
    rates = {
        karat: (inr_per_gram_24k_spot * factor).quantize(Decimal('1'))
        for karat, factor in PURITY.items()
    }
    return {
        'rates': rates,
        'source': 'gold-api.com (international spot)',
        'city': None,
        'fetched_at': timezone.now(),
        'usd_per_oz': usd_per_oz.quantize(Decimal('0.01')),
        'usd_inr':    usd_inr.quantize(Decimal('0.01')),
        'stale': False,
    }


def _fetch_from_db():
    """Final fallback: use the latest GoldRate row per purity from any tenant."""
    from .models import GoldRate
    from apps.iam.models import Tenant

    rates = {}
    tenant = Tenant.objects.first()
    if tenant is None:
        return None
    for karat in (24, 22, 18):
        gr = GoldRate.latest_for(tenant, Decimal(karat))
        if gr:
            rates[karat] = Decimal(gr.rate_per_gram.amount).quantize(Decimal('1'))

    if not rates:
        return None

    base = rates.get(22) or rates.get(24) or rates.get(18)
    if base:
        scale_from = 22 if 22 in rates else (24 if 24 in rates else 18)
        for karat in (24, 22, 18):
            if karat not in rates:
                rates[karat] = (Decimal(base) * Decimal(karat) /
                                Decimal(scale_from)).quantize(Decimal('1'))

    return {
        'rates': rates,
        'source': 'manual (latest GoldRate entry)',
        'city': None,
        'fetched_at': timezone.now(),
        'usd_per_oz': None,
        'usd_inr': None,
        'stale': True,
    }
