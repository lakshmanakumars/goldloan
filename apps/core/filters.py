"""Unfold range filters that use flatpickr for date entry.

Unfold's stock RangeDate/RangeDateTime filters render their date inputs with
the ``vCustomDateField``/``vCustomTimeField`` classes and load
``DateTimeShortcuts.js``, which injects a second calendar/clock picker — a
different, clunkier experience than the flatpickr picker used on the forms
(see apps.core.forms).

These filters instead:
  * swap ``vCustomDateField`` → ``flatpickr-date`` so the existing
    ``static/vaarahi/admin-datepicker.js`` attaches flatpickr (matching forms);
  * drop the ``DateTimeShortcuts.js`` media so no second picker is injected;
  * for DateTimeField columns, render a *date-only* range (no time box) and
    filter on a tz-aware half-open ``[from 00:00, to+1day 00:00)`` window so
    the whole "to" day is included — without ``__date`` lookups, which need
    MySQL's timezone tables (often not loaded) and silently match nothing.
"""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.contrib.filters.forms import RangeDateForm


def _flatpickrize(widget):
    """Replace the vCustomDateField hook with flatpickr-date, recursing into
    composite widgets so only the date input is swapped."""
    subwidgets = getattr(widget, 'widgets', None)
    if subwidgets:
        for sub in subwidgets:
            _flatpickrize(sub)
        return
    cls = widget.attrs.get('class', '')
    if 'vCustomDateField' in cls:
        widget.attrs['class'] = cls.replace('vCustomDateField', 'flatpickr-date')


def _parse_date(val):
    if not val:
        return None
    for fmt in ('%d-%m-%Y', '%Y-%m-%d'):  # flatpickr d-m-Y, then ISO
        try:
            return datetime.strptime(val, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


class FlatpickrRangeDateForm(RangeDateForm):
    # No DateTimeShortcuts.js — flatpickr (loaded globally) handles the inputs,
    # so the stock second calendar is never injected.
    class Media:
        js = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            _flatpickrize(field.widget)


class FlatpickrRangeDateFilter(RangeDateFilter):
    """Flatpickr date range for a DateField column."""
    form_class = FlatpickrRangeDateForm


class FlatpickrRangeDateTimeFilter(RangeDateFilter):
    """Flatpickr **date-only** range for a DateTimeField column.

    DateTimeField subclasses DateField, so RangeDateFilter accepts it. We keep
    a clean two-date UI (no time inputs) and translate the dates into a
    tz-aware datetime window that includes the entire "to" day.
    """
    form_class = FlatpickrRangeDateForm

    def queryset(self, request, queryset):
        filters = {}
        tz = timezone.get_current_timezone()
        df = _parse_date(self.used_parameters.get(self.parameter_name + '_from'))
        dt = _parse_date(self.used_parameters.get(self.parameter_name + '_to'))
        if df:
            filters[self.parameter_name + '__gte'] = timezone.make_aware(
                datetime.combine(df, time.min), tz)
        if dt:
            filters[self.parameter_name + '__lt'] = timezone.make_aware(
                datetime.combine(dt + timedelta(days=1), time.min), tz)
        try:
            return queryset.filter(**filters)
        except (ValueError, ValidationError):
            return None
