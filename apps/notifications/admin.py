from django.contrib import admin
from django.utils.html import format_html
from urllib.parse import quote
from unfold.contrib.filters.admin import ChoicesDropdownFilter
from apps.core.admin import TenantModelAdmin
from apps.core.filters import (
    FlatpickrRangeDateFilter, FlatpickrRangeDateTimeFilter)
from .models import InterestReminder


@admin.register(InterestReminder)
class InterestReminderAdmin(TenantModelAdmin):
    tenant_resource = 'reminder'
    list_display = ('loan', 'period_month', 'channel', 'interest_due',
                    'status', 'sent_at', 'whatsapp_btn')
    list_filter = (
        ('status', ChoicesDropdownFilter),
        ('channel', ChoicesDropdownFilter),
        ('period_month', FlatpickrRangeDateFilter),
        ('sent_at', FlatpickrRangeDateTimeFilter),
    )
    search_fields = ('loan__loan_no', 'to_phone', 'message')
    readonly_fields = ('sent_at', 'created_at', 'updated_at', 'error')

    def whatsapp_btn(self, obj):
        digits = ''.join(c for c in (obj.to_phone or '') if c.isdigit())
        if len(digits) == 10:
            digits = '91' + digits
        if not digits:
            return '—'
        url = f'https://wa.me/{digits}?text={quote(obj.message or "")}'
        return format_html(
            '<a href="{}" target="_blank" class="vh-btn vh-btn-whatsapp vh-btn-sm">'
            '<span class="material-symbols-outlined">chat</span>Send</a>', url)
    whatsapp_btn.short_description = 'WhatsApp'
