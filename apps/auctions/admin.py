from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.core.admin import TenantModelAdmin
from .models import Auction, AuctionNotice


@admin.register(Auction)
class AuctionAdmin(TenantModelAdmin):
    tenant_resource = 'auction'
    list_display = ('loan_link', 'customer', 'status_pill', 'eligible_at',
                    'notice1_sent_at', 'notice2_sent_at', 'scheduled_at',
                    'sold_amount_display', 'tools')
    list_filter = ('status',)
    search_fields = ('loan__loan_no', 'loan__customer__name', 'bidder_name')
    readonly_fields = ('loan', 'eligible_at', 'notice1_sent_at',
                       'notice2_sent_at', 'surplus_refunded_at',
                       'created_at', 'updated_at')

    STATUS_PILL = {
        'eligible':     ('#FEE2E2', '#991B1B', 'Eligible'),
        'notice1_sent': ('#FEF3C7', '#92400E', 'Notice 1 sent'),
        'notice2_sent': ('#FED7AA', '#9A3412', 'Notice 2 sent'),
        'scheduled':    ('#DBEAFE', '#1E40AF', 'Scheduled'),
        'sold':         ('#E0E7FF', '#3730A3', 'Sold'),
        'posted':       ('#E5E7EB', '#374151', 'Posted'),
        'cancelled':    ('#DCFCE7', '#166534', 'Cancelled'),
    }

    def status_pill(self, obj):
        bg, fg, label = self.STATUS_PILL.get(obj.status,
                                             ('#E5E7EB', '#374151', obj.status))
        return format_html(
            '<span style="display:inline-block;padding:2px 10px;'
            'border-radius:999px;font-size:10.5px;font-weight:700;'
            'text-transform:uppercase;letter-spacing:.04em;'
            'background:{};color:{}">{}</span>',
            bg, fg, label)
    status_pill.short_description = 'Status'
    status_pill.admin_order_field = 'status'

    def loan_link(self, obj):
        url = reverse('loans:detail', args=[obj.loan_id])
        return format_html(
            '<a href="{}" style="color:#c46616;font-weight:700">{}</a>',
            url, obj.loan.loan_no)
    loan_link.short_description = 'Loan'
    loan_link.admin_order_field = 'loan__loan_no'

    def customer(self, obj):
        url = reverse('customers:detail', args=[obj.loan.customer_id])
        return format_html(
            '<a href="{}" style="color:#c46616">{}</a>',
            url, obj.loan.customer.name)

    def sold_amount_display(self, obj):
        if obj.sold_amount and obj.sold_amount.amount:
            return f'₹{obj.sold_amount.amount:,.2f}'
        return '—'
    sold_amount_display.short_description = 'Sold for'

    def tools(self, obj):
        url = reverse('auctions:detail', args=[obj.pk])
        return format_html(
            '<a href="{}" class="vh-btn vh-btn-primary vh-btn-sm">'
            '<span class="material-symbols-outlined">visibility</span>Open</a>',
            url)
    tools.short_description = 'Actions'


@admin.register(AuctionNotice)
class AuctionNoticeAdmin(TenantModelAdmin):
    tenant_resource = 'auction'
    list_display = ('auction', 'notice_no', 'sent_at', 'channels',
                    'sent_by', 'pdf_link')
    list_filter = ('notice_no',)
    search_fields = ('auction__loan__loan_no',)
    readonly_fields = ('auction', 'notice_no', 'sent_at', 'channels',
                       'delivery_ref', 'pdf_path', 'sent_by',
                       'created_at', 'updated_at')

    def pdf_link(self, obj):
        if obj.pdf_path:
            return format_html(
                '<a href="{}" target="_blank" class="vh-btn vh-btn-accent vh-btn-sm">'
                '<span class="material-symbols-outlined">picture_as_pdf</span>'
                'PDF</a>', obj.pdf_path.url)
        return '—'
    pdf_link.short_description = 'PDF'
