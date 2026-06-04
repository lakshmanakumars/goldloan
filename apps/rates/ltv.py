"""LTV (Loan-to-Value) calculator.

Inputs:
    tenant      — apps.iam.Tenant
    items       — iterable of loans.GoldItem (saved or unsaved)
    on_date     — date for rate lookup; defaults to today

Returns a dict with:
    rates_used        : {purity_carat -> rate_per_gram}
    item_breakdown    : [{description, net_wt, purity, rate, value}]
    gross_value       : total gold value (sum across items)
    max_ltv_pct       : tenant's policy
    eligible_principal: gross_value * max_ltv_pct / 100
    warnings          : list of strings (e.g. missing rate)
"""
from decimal import Decimal
from django.utils import timezone


def compute(tenant, items, on_date=None):
    from .models import GoldRate
    on_date = on_date or timezone.localdate()
    warnings = []
    rates_used = {}
    breakdown = []
    gross = Decimal('0.00')

    for it in items:
        purity = Decimal(it.purity_carat).quantize(Decimal('0.01'))
        rate_row = GoldRate.latest_for(tenant, purity, on_date)
        if rate_row is None:
            # Fall back: try 22ct rate if not found, scale by purity ratio
            fallback = GoldRate.latest_for(tenant, Decimal('22.00'), on_date)
            if fallback is None:
                warnings.append(
                    f'No gold rate for {purity}ct (or 22ct fallback) on/before '
                    f'{on_date}. Skipping item "{it.description}".'
                )
                breakdown.append({
                    'description': it.description, 'net_wt': it.net_weight_g,
                    'purity': purity, 'rate_per_g': None, 'value': Decimal('0.00'),
                })
                continue
            rate_per_g = (fallback.rate_per_gram.amount * purity
                          / Decimal('22.00')).quantize(Decimal('0.01'))
            warnings.append(
                f'No direct {purity}ct rate; scaled 22ct rate by purity ratio.')
        else:
            rate_per_g = rate_row.rate_per_gram.amount
            rates_used[str(purity)] = rate_per_g

        value = (Decimal(it.net_weight_g) * rate_per_g).quantize(Decimal('0.01'))
        gross += value
        breakdown.append({
            'description': it.description, 'net_wt': it.net_weight_g,
            'purity': purity, 'rate_per_g': rate_per_g, 'value': value,
        })

    max_ltv = Decimal(getattr(tenant, 'max_ltv_pct', '75.00'))
    eligible = (gross * max_ltv / Decimal('100')).quantize(Decimal('0.01'))

    return {
        'rates_used': rates_used,
        'item_breakdown': breakdown,
        'gross_value': gross.quantize(Decimal('0.01')),
        'max_ltv_pct': max_ltv,
        'eligible_principal': eligible,
        'warnings': warnings,
    }
