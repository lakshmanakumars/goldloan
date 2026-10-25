"""Password validators.

ComplexityValidator requires at least one uppercase letter, one lowercase
letter, one digit and one special character, on top of Django's built-in
length / common-password checks configured in AUTH_PASSWORD_VALIDATORS.
"""
import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class ComplexityValidator:
    RULES = [
        (r'[A-Z]', 'one uppercase letter'),
        (r'[a-z]', 'one lowercase letter'),
        (r'[0-9]', 'one digit'),
        (r'[^A-Za-z0-9]', 'one special character (e.g. ! @ # - _)'),
    ]

    def validate(self, password, user=None):
        missing = [label for pattern, label in self.RULES
                   if not re.search(pattern, password)]
        if missing:
            raise ValidationError(
                _('Password must contain at least %(missing)s.')
                % {'missing': ', '.join(missing)},
                code='password_too_simple',
            )

    def get_help_text(self):
        return _('Your password must contain an uppercase letter, a lowercase '
                 'letter, a digit and a special character.')
