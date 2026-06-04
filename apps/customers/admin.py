from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from apps.core.admin import TenantModelAdmin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(TenantModelAdmin):
    tenant_resource = 'customer'
    list_display = ('code_link', 'name_link', 'phone', 'city', 'tools', 'created_at')
    list_display_links = None  # disable auto-link to change form
    show_full_result_count = False
    list_filter = ('gender', 'city', 'state', 'preferred_language')
    search_fields = ('code', 'name', 'phone', 'pan', 'aadhaar')
    readonly_fields = ('code', 'created_at', 'updated_at')

    def code_link(self, obj):
        url = reverse('customers:detail', args=[obj.pk])
        return format_html(
            '<a href="{}" style="color:#c46616;font-weight:700;'
            'text-decoration:none;font-variant-numeric:tabular-nums">{}</a>',
            url, obj.code)
    code_link.short_description = 'Code'
    code_link.admin_order_field = 'code'

    def name_link(self, obj):
        url = reverse('customers:detail', args=[obj.pk])
        return format_html(
            '<a href="{}" style="color:#c46616;font-weight:600;'
            'text-decoration:none">{}</a>',
            url, obj.name)
    name_link.short_description = 'Name'
    name_link.admin_order_field = 'name'

    def tools(self, obj):
        if not obj.pk:
            return '—'
        view_url = reverse('customers:detail', args=[obj.pk])
        wa = obj.whatsapp_link()
        wa_html = mark_safe('')
        if wa:
            wa_html = format_html(
                '<a href="{}" target="_blank" class="vh-btn vh-btn-whatsapp vh-btn-sm" '
                'style="margin-right:4px"><span class="material-symbols-outlined">'
                'chat</span>WA</a>', wa)
        return format_html(
            '<a href="{}" class="vh-btn vh-btn-primary vh-btn-sm" style="margin-right:4px">'
            '<span class="material-symbols-outlined">visibility</span>Profile</a>{}',
            view_url, wa_html,
        )
    tools.short_description = 'Actions'
    fieldsets = (
        ('Identity', {
            'fields': ('code', 'name', 'dob', 'gender', 'photo'),
        }),
        ('Contact', {
            'fields': ('phone', 'alt_phone', 'email'),
        }),
        ('KYC', {
            'fields': ('pan', 'aadhaar', 'id_proof', 'preferred_language'),
        }),
        ('Address', {
            'fields': ('address_line1', 'address_line2', 'city', 'state',
                       'pincode'),
        }),
        ('Misc', {
            'fields': ('notes', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

