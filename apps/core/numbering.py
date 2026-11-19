"""Shared auto-numbering for document numbers (loan no, receipt no, customer
code, ...).

Every generated number is ``<prefix><zero-padded sequence>`` and is protected
by a per-tenant unique constraint. Two rules keep generation collision-proof:

1. **Next = highest sequence already issued under the prefix + 1.**
   Never derive it from a row count, a date-range count or a primary key:
   counts go wrong as soon as a row is deleted, back-dated or imported, and
   then every retry regenerates the same taken number (this is what caused
   the 500 on repayment add in Nov 2026).

2. **On a collision, regenerate and retry.** A concurrent insert can take the
   number between generation and insert; because rule 1 reads the current
   maximum, the retry picks the next free one.

Use :func:`next_number` to generate and :func:`save_with_auto_number` to
insert.
"""
import logging
import re

from django.db import IntegrityError, transaction
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr

logger = logging.getLogger(__name__)

MAX_RETRIES = 10

_SAFE_PREFIX = re.compile(r'^[A-Za-z0-9-]*$')


def next_number(qs, field, prefix, width):
    """Return ``prefix`` + (highest numeric suffix in ``qs.<field>`` + 1).

    ``qs`` must already be scoped to the uniqueness scope (normally the
    tenant). Values under the prefix whose suffix is not purely numeric
    (e.g. a hand-typed ``C-OLD1``) are ignored rather than breaking the
    sequence.
    """
    if not _SAFE_PREFIX.match(prefix):
        raise ValueError(f'unsupported number prefix: {prefix!r}')
    last = qs.filter(
        **{f'{field}__regex': rf'^{prefix}[0-9]+$'},
    ).annotate(
        _seq=Cast(Substr(field, len(prefix) + 1), IntegerField()),
    ).aggregate(m=Max('_seq'))['m'] or 0
    return f'{prefix}{last + 1:0{width}d}'


def save_with_auto_number(instance, field, generate, save, taken_qs):
    """Insert ``instance`` with ``instance.<field>`` set by ``generate()``,
    regenerating and retrying if the number is taken concurrently.

    ``save`` performs the real insert (usually ``super().save`` bound with
    the caller's args). ``taken_qs`` is the queryset the number must be
    unique within; it is used to tell a number collision (retry) from any
    other integrity error (re-raise immediately, retrying cannot fix it).
    """
    setattr(instance, field, generate())
    for attempt in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                save()
            return
        except IntegrityError:
            value = getattr(instance, field)
            collided = taken_qs.filter(**{field: value}).exists()
            if not collided or attempt == MAX_RETRIES - 1:
                raise
            logger.warning('%s %s=%s already taken, regenerating (attempt %d)',
                           type(instance).__name__, field, value, attempt + 1)
            setattr(instance, field, generate())
