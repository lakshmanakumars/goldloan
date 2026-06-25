from django.apps import AppConfig


class LoansConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.loans'

    def ready(self):
        # Wire the signal that auto-closes a loan once it's fully settled.
        from . import signals  # noqa: F401
