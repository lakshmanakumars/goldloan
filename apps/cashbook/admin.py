from decimal import Decimal

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter, RelatedDropdownFilter)

from apps.core.admin import TenantModelAdmin
from apps.core.filters import FlatpickrRangeDateFilter
from .models import CashTransaction, DayClose


@admin.register(CashTransaction)
class CashTransactionAdmin(TenantModelAdmin):
    tenant_resource = 'cashbook'
    list_display = ('txn_date', 'kind_pill', 'amount_display', 'mode',
                    'party', 'note_short', 'created_by', 'auto_badge')
    list_filter = (
        ('kind', ChoicesDropdownFilter),
        ('mode', ChoicesDropdownFilter),
        ('branch', RelatedDropdownFilter),
        ('txn_date', FlatpickrRangeDateFilter),
    )
    search_fields = ('note', 'source_loan__loan_no',
                     'source_repayment__loan__loan_no')
    date_hierarchy = 'txn_date'
    readonly_fields = ('source_loan', 'source_repayment', 'created_by',
                       'created_at', 'updated_at')
    fieldsets = (
        ('Entry', {
            'fields': ('txn_date', 'kind', 'amount', 'mode', 'branch', 'note'),
        }),
        ('Auto link', {
            'fields': ('source_loan', 'source_repayment'),
            'classes': ('collapse',),
        }),
        ('System', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        # Auto-posted rows are fully read-only
        if obj and obj.is_auto:
            return tuple(f.name for f in obj._meta.fields)
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Cannot delete auto-posted rows (they mirror loan/repayment state)
        if obj and obj.is_auto:
            return False
        return super().has_delete_permission(request, obj)

    # ---- list display helpers ----

    KIND_COLORS = {
        'opening':         ('#FEF3C7', '#92400E'),
        'disburse_out':    ('#FEE2E2', '#991B1B'),
        'repayment_in':    ('#DCFCE7', '#166534'),
        'capital_in':      ('#DBEAFE', '#1E40AF'),
        'drawal_out':      ('#FED7AA', '#9A3412'),
        'expense_out':     ('#FCE7F3', '#9D174D'),
        'bank_deposit':    ('#E5E7EB', '#374151'),
        'bank_withdrawal': ('#E5E7EB', '#374151'),
        'adjustment':      ('#FEF9C3', '#854D0E'),
    }

    def kind_pill(self, obj):
        bg, fg = self.KIND_COLORS.get(obj.kind, ('#E5E7EB', '#374151'))
        return format_html(
            '<span style="display:inline-block;padding:2px 10px;'
            'border-radius:999px;font-size:10.5px;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.04em;'
            'background:{};color:{}">{}</span>',
            bg, fg, obj.get_kind_display())
    kind_pill.short_description = 'Kind'
    kind_pill.admin_order_field = 'kind'

    def amount_display(self, obj):
        if obj.kind in obj.OUT_KINDS:
            return format_html(
                '<span style="color:#991B1B;font-weight:600;'
                'font-variant-numeric:tabular-nums">− ₹{}</span>',
                f'{obj.amount.amount:,.2f}')
        return format_html(
            '<span style="color:#166534;font-weight:600;'
            'font-variant-numeric:tabular-nums">+ ₹{}</span>',
            f'{obj.amount.amount:,.2f}')
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'

    def party(self, obj):
        if obj.source_loan_id:
            url = reverse('loans:detail', args=[obj.source_loan_id])
            return format_html(
                '<a href="{}" style="color:#c46616;text-decoration:none">{}</a>',
                url, obj.source_loan.customer.name)
        if obj.source_repayment_id:
            url = reverse('loans:repayment_detail', args=[obj.source_repayment_id])
            return format_html(
                '<a href="{}" style="color:#c46616;text-decoration:none">{}</a>',
                url, obj.source_repayment.loan.customer.name)
        return '—'
    party.short_description = 'Party'

    def note_short(self, obj):
        n = obj.note or ''
        return n[:60] + ('…' if len(n) > 60 else '')
    note_short.short_description = 'Note'

    def auto_badge(self, obj):
        if obj.is_auto:
            return format_html(
                '<span style="font-size:10px;color:#6b7280">AUTO</span>')
        return ''
    auto_badge.short_description = ''


@admin.register(DayClose)
class DayCloseAdmin(TenantModelAdmin):
    tenant_resource = 'cashbook'
    list_display = ('close_date', 'branch', 'opening_balance_display',
                    'computed_in_display', 'computed_out_display',
                    'closing_balance_display', 'physical_count_display',
                    'variance_display', 'closed_by')
    list_filter = (
        ('branch', RelatedDropdownFilter),
        ('close_date', FlatpickrRangeDateFilter),
    )
    date_hierarchy = 'close_date'
    readonly_fields = ('opening_balance', 'computed_in', 'computed_out',
                       'closing_balance', 'variance', 'closed_by',
                       'created_at', 'updated_at')
    fieldsets = (
        ('Close', {
            'fields': ('close_date', 'branch'),
        }),
        ('Computed', {
            'fields': ('opening_balance', 'computed_in', 'computed_out',
                       'closing_balance'),
        }),
        ('Physical', {
            'fields': ('physical_count', 'variance', 'denomination_json',
                       'notes'),
        }),
        ('System', {
            'fields': ('closed_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        # Compute opening/in/out/closing/variance from CashTransaction
        from .services import cash_position
        pos = cash_position(obj.tenant or request.tenant,
                            on_date=obj.close_date, branch=obj.branch)
        from djmoney.money import Money
        obj.opening_balance = Money(pos.opening, 'INR')
        obj.computed_in = Money(pos.inflow, 'INR')
        obj.computed_out = Money(pos.outflow, 'INR')
        obj.closing_balance = Money(pos.closing, 'INR')
        if obj.physical_count:
            obj.variance = Money(
                Decimal(obj.physical_count.amount) - pos.closing, 'INR')
        else:
            obj.physical_count = Money(pos.closing, 'INR')
            obj.variance = Money(Decimal('0'), 'INR')
        if not change and not obj.closed_by_id:
            obj.closed_by = request.user
        super().save_model(request, obj, form, change)

    # ---- list helpers ----

    def _money_td(self, m, color=None):
        amt = m.amount if hasattr(m, 'amount') else Decimal(m or 0)
        style = 'font-variant-numeric:tabular-nums'
        if color:
            style += f';color:{color}'
        return format_html('<span style="{}">₹{}</span>', style,
                           f'{amt:,.2f}')

    def opening_balance_display(self, obj):
        return self._money_td(obj.opening_balance)
    opening_balance_display.short_description = 'Opening'

    def computed_in_display(self, obj):
        return self._money_td(obj.computed_in, '#166534')
    computed_in_display.short_description = 'In'

    def computed_out_display(self, obj):
        return self._money_td(obj.computed_out, '#991B1B')
    computed_out_display.short_description = 'Out'

    def closing_balance_display(self, obj):
        return self._money_td(obj.closing_balance)
    closing_balance_display.short_description = 'Closing'

    def physical_count_display(self, obj):
        return self._money_td(obj.physical_count)
    physical_count_display.short_description = 'Physical'

    def variance_display(self, obj):
        v = Decimal(obj.variance.amount if hasattr(obj.variance, 'amount') else 0)
        if v == 0:
            return format_html(
                '<span class="vh-pill vh-pill-active">OK</span>')
        if abs(v) <= Decimal('10'):
            return format_html(
                '<span class="vh-pill vh-pill-trial">±₹{}</span>',
                f'{abs(v):,.2f}')
        return format_html(
            '<span class="vh-pill vh-pill-overdue">±₹{}</span>',
            f'{abs(v):,.2f}')
    variance_display.short_description = 'Variance'
