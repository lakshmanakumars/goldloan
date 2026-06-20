"""Custom date/time formats for the app (loaded via FORMAT_MODULE_PATH).

`LANGUAGE_CODE = 'en-in'` has no dedicated format module in Django, so it falls
back to the US `en` defaults (e.g. `2026-06-20`). This module overrides the
`en` fallback to use Indian day-first formatting (`20-06-2026`) everywhere —
form inputs, list display, and value rendering.
"""

# How dates are DISPLAYED.
DATE_FORMAT = 'd-m-Y'              # 20-06-2026
SHORT_DATE_FORMAT = 'd-m-Y'
DATETIME_FORMAT = 'd-m-Y H:i'      # 20-06-2026 14:30
SHORT_DATETIME_FORMAT = 'd-m-Y H:i'

# What the form fields ACCEPT when the user types / a widget submits.
# First entry is also what AdminDateWidget renders the value as.
DATE_INPUT_FORMATS = [
    '%d-%m-%Y',   # 20-06-2026  (primary)
    '%d/%m/%Y',   # 20/06/2026
    '%Y-%m-%d',   # 2026-06-20  (ISO, kept for compatibility / pasted values)
]

DATETIME_INPUT_FORMATS = [
    '%d-%m-%Y %H:%M:%S',
    '%d-%m-%Y %H:%M',
    '%d-%m-%Y',
    '%d/%m/%Y %H:%M',
    '%d/%m/%Y',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d',
]
