import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

app = Celery('goldloan')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Monthly interest reminder on the 1st of every month at 09:00 IST
app.conf.beat_schedule = {
    # Monthly interest reminders on the 1st at 09:00 IST
    'send-monthly-interest-reminders': {
        'task': 'apps.notifications.tasks.send_monthly_interest_reminders',
        'schedule': crontab(minute=0, hour=9, day_of_month=1),
    },
    # Nightly NPA classifier at 01:00 IST
    'classify-npa-nightly': {
        'task': 'apps.loans.tasks.classify_npa_all_tenants',
        'schedule': crontab(minute=0, hour=1),
    },
    # Refresh live gold rate cache every 15 minutes so the ticker is
    # always warm (cache TTL matches).
    'refresh-live-gold-rates': {
        'task': 'apps.rates.tasks.refresh_live_gold_rates',
        'schedule': crontab(minute='*/15'),
    },
}


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
