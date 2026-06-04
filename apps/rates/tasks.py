"""Celery task to keep the live gold-rate cache warm."""
import logging
from celery import shared_task

log = logging.getLogger(__name__)


@shared_task(bind=True, name='apps.rates.tasks.refresh_live_gold_rates')
def refresh_live_gold_rates(self):
    from .live import get_live_rates
    data = get_live_rates(force_refresh=True)
    if not data:
        log.warning('refresh_live_gold_rates: fetch returned nothing')
        return 'no data'
    rates = data['rates']
    summary = (
        f"refreshed (source={data['source']}) "
        f"24K=₹{rates[24]} 22K=₹{rates[22]} 18K=₹{rates[18]}"
    )
    log.info(summary)
    return summary
