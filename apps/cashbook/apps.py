from django.apps import AppConfig


class CashbookConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.cashbook'
    verbose_name = 'Cash Book'

    def ready(self):
        # Wire signals to auto-post Loan disbursements and Repayments
        # into the cash book.
        from . import signals  # noqa: F401
