from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import TabularInline
from apps.core.admin import TenantModelAdmin
from apps.core.permissions import role_can, R, W
from .models import Loan, GoldItem, Repayment


class _TenantInlineMixin:
    """Permission methods for inlines on tenant-scoped models.

    Delegates to the role matrix using a `tenant_resource` key on the
    inline class (e.g. 'gold_item', 'repayment').
    """
    tenant_resource = None

    def _tenant_ok(self, request):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        tenant = getattr(request, 'tenant', None)
        return (tenant is not None and user.is_staff
                and user.tenant_id == tenant.id)

    def has_view_permission(self, request, obj=None):
        return self._tenant_ok(request) and role_can(
            request.user, self.tenant_resource, R)

    def has_add_permission(self, request, obj=None):
        return self._tenant_ok(request) and role_can(
            request.user, self.tenant_resource, W)

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)


class GoldItemInline(_TenantInlineMixin, TabularInline):
    model = GoldItem
    tenant_resource = 'gold_item'
    extra = 1
    fields = ('description', 'gross_weight_g', 'stone_weight_g',
              'net_weight_g', 'purity_carat', 'rate_per_gram', 'photo')

    def get_extra(self, request, obj=None, **kwargs):
        # On edit (existing loan) show no blank row by default — only the
        # "Add another Gold item" button adds one. On add, keep one blank row.
        return 0 if obj else 1


class RepaymentInline(_TenantInlineMixin, TabularInline):
    model = Repayment
    tenant_resource = 'repayment'
    extra = 0
    fields = ('paid_at', 'principal_paid', 'interest_paid', 'mode',
              'reference', 'receipt_no')
    readonly_fields = ('paid_at',)


@admin.register(Loan)
class LoanAdmin(TenantModelAdmin):
    tenant_resource = 'loan'
    list_display = ('loan_no_link', 'customer', 'principal', 'outstanding_display',
                    'interest_due_display', 'rate_display',
                    'maturity_date', 'status', 'tools')
    # Clicking a row opens the read-only detail page (not the edit form);
    # editing is reached from a button on that detail page.
    list_display_links = None
    list_filter = ('status', 'rate_type', 'start_date')
    search_fields = ('loan_no', 'customer__name', 'customer__phone',
                     'packet_no')
    readonly_fields = ('loan_no', 'maturity_date', 'closed_at',
                       'renewed_to', 'created_at', 'updated_at',
                       'ltv_summary', 'balance_summary',
                       'ltv_eligible_principal')
    inlines = [GoldItemInline, RepaymentInline]
    autocomplete_fields = ['customer']
    # Add-form ordering: brand-new loan. Walk the user through the workflow:
    # pick borrower → set terms → record storage. LTV/Balance/Lifecycle make
    # sense only after the first save (when items + repayments exist), so
    # they're omitted here to keep the form clean.
    add_fieldsets = (
        ('Borrower', {
            'fields': ('customer', 'branch'),
            'description': 'Pick the customer and (optionally) the branch. '
                           'Add gold items in the section below to see live '
                           'LTV-derived eligibility before you set principal.',
        }),
        ('Eligibility (LTV)', {
            'fields': ('ltv_summary',),
            'description': 'Live — recomputes as you edit the gold-items '
                           'rows above (no save needed).',
        }),
        ('Loan terms', {
            'fields': ('ltv_eligible_principal', 'principal',
                       ('rate_type', 'interest_rate_pct'),
                       ('tenure_months', 'start_date'),
                       'status'),
        }),
        ('Storage & notes', {
            'fields': ('packet_no', 'purpose', 'notes'),
        }),
    )

    # Change-form ordering: existing loan. Eligibility first (so the user
    # sees the LTV breakdown from existing items before tweaking principal),
    # then the loan terms, balance, storage, lifecycle, and system fields.
    change_fieldsets = (
        ('Borrower', {
            'fields': ('loan_no', 'customer', 'branch'),
        }),
        ('Eligibility (LTV)', {
            'fields': ('ltv_summary',),
            'description': 'Derived from the gold items (added below) and the '
                           'latest gold rates.',
        }),
        ('Loan terms', {
            'fields': ('ltv_eligible_principal', 'principal',
                       ('rate_type', 'interest_rate_pct'),
                       ('tenure_months', 'start_date', 'maturity_date'),
                       'status'),
        }),
        ('Balance', {
            'fields': ('balance_summary',),
            'description': 'Live balance from all repayments below.',
        }),
        ('Storage & notes', {
            'fields': ('packet_no', 'purpose', 'notes'),
        }),
        ('Lifecycle', {
            'fields': ('closed_at', 'renewed_to'),
            'description': 'Top-up, Renew and Pre-close are available from '
                           'the buttons on the loan detail page.',
        }),
        ('System', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        return self.change_fieldsets if obj else self.add_fieldsets

    class Media:
        # Live LTV recompute for the inline gold-item rows (before save).
        js = ('admin/loans/loan_ltv_live.js',)

    def render_change_form(self, request, context, add=False, change=False,
                           form_url='', obj=None):
        """Inject the tenant's gold rates + max-LTV into the page so the
        client-side JS can recompute LTV from unsaved inline rows."""
        from decimal import Decimal
        from apps.core.tenancy import get_current_tenant
        from apps.rates.models import GoldRate

        tenant = (obj.tenant if (obj and obj.tenant_id)
                  else get_current_tenant())
        rates = {}
        fallback_22ct = None
        if tenant is not None:
            today = timezone.localdate()
            purities = (GoldRate.all_objects
                        .filter(tenant=tenant)
                        .values_list('purity_carat', flat=True)
                        .distinct())
            for p in purities:
                r = GoldRate.latest_for(tenant, p, today)
                if r is not None:
                    rates[f'{Decimal(p):.2f}'] = float(r.rate_per_gram.amount)
            fb = GoldRate.latest_for(tenant, Decimal('22.00'), today)
            if fb is not None:
                fallback_22ct = float(fb.rate_per_gram.amount)

        context['ltv_data'] = {
            'rates': rates,
            'fallback_22ct': fallback_22ct,
            'max_ltv_pct': float(tenant.max_ltv_pct) if tenant else 75.0,
        }
        return super().render_change_form(
            request, context, add=add, change=change,
            form_url=form_url, obj=obj)

    def rate_display(self, obj):
        suffix = '% p.m.' if obj.rate_type == obj.RateType.MONTHLY else '% p.a.'
        return f'{obj.interest_rate_pct}{suffix}'
    rate_display.short_description = 'Interest rate'
    rate_display.admin_order_field = 'interest_rate_pct'

    def outstanding_display(self, obj):
        if not obj.pk:
            return '—'
        outstanding = obj.outstanding_principal().amount
        original = obj.principal.amount
        paid = original - outstanding
        if paid <= 0:
            # Nothing paid yet — show outstanding plain
            return format_html(
                '<span style="font-variant-numeric:tabular-nums">'
                '₹{}</span>', f'{outstanding:,.2f}')
        # Some principal repaid — colour green and show "paid" hint
        return format_html(
            '<span style="font-variant-numeric:tabular-nums;color:#047857;'
            'font-weight:600">₹{}</span>'
            '<br><span style="font-size:10px;color:#6b7280">'
            'paid ₹{}</span>',
            f'{outstanding:,.2f}', f'{paid:,.2f}',
        )
    outstanding_display.short_description = 'Outstanding'

    def interest_due_display(self, obj):
        if not obj.pk:
            return '—'
        due = obj.interest_due_now().amount
        days = obj.days_outstanding()
        if due <= 0:
            return format_html(
                '<span style="font-variant-numeric:tabular-nums;color:#047857">'
                '₹0.00</span><br><span style="font-size:10px;color:#6b7280">'
                'all paid</span>')
        return format_html(
            '<span style="font-variant-numeric:tabular-nums;color:#991b1b;'
            'font-weight:600">₹{}</span>'
            '<br><span style="font-size:10px;color:#6b7280">'
            'over {} days</span>',
            f'{due:,.2f}', days,
        )
    interest_due_display.short_description = 'Interest due'

    def balance_summary(self, obj):
        if not obj.pk:
            return format_html(
                '<span style="color:#6b7280">Save the loan first.</span>')
        original = obj.principal.amount
        paid_p = obj.total_paid_principal().amount
        paid_i = obj.total_paid_interest().amount
        outstanding = obj.outstanding_principal().amount
        monthly = obj.monthly_interest().amount
        days = obj.days_outstanding()
        months = obj.months_charged()
        accrued = obj.interest_accrued().amount
        interest_due = obj.interest_due_now().amount
        total_due = outstanding + interest_due
        return format_html(
            '<table style="width:100%;max-width:600px;border-collapse:collapse;font-size:13px">'
            '<tr><td style="padding:6px 10px;color:#6b7280">Original principal</td>'
            '<td style="padding:6px 10px;text-align:right;font-variant-numeric:tabular-nums">₹{}</td></tr>'
            '<tr><td style="padding:6px 10px;color:#6b7280">Total principal paid</td>'
            '<td style="padding:6px 10px;text-align:right;font-variant-numeric:tabular-nums;color:#047857">₹{}</td></tr>'
            '<tr style="background:#fef3c7"><td style="padding:8px 10px;font-weight:700">Outstanding principal</td>'
            '<td style="padding:8px 10px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums">₹{}</td></tr>'
            '<tr><td colspan="2" style="border-top:1px solid #e5e7eb;padding-top:8px"></td></tr>'
            '<tr><td style="padding:6px 10px;color:#6b7280">Days outstanding</td>'
            '<td style="padding:6px 10px;text-align:right">{} days &middot; {} month(s) charged</td></tr>'
            '<tr><td style="padding:6px 10px;color:#6b7280">Monthly interest @ {}% {}</td>'
            '<td style="padding:6px 10px;text-align:right;font-variant-numeric:tabular-nums">₹{}</td></tr>'
            '<tr><td style="padding:6px 10px;color:#6b7280">Interest accrued to date</td>'
            '<td style="padding:6px 10px;text-align:right;font-variant-numeric:tabular-nums">₹{}</td></tr>'
            '<tr><td style="padding:6px 10px;color:#6b7280">Interest paid so far</td>'
            '<td style="padding:6px 10px;text-align:right;font-variant-numeric:tabular-nums;color:#047857">₹{}</td></tr>'
            '<tr style="background:#fee2e2"><td style="padding:8px 10px;font-weight:700">Interest due now</td>'
            '<td style="padding:8px 10px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums;color:#991b1b">₹{}</td></tr>'
            '<tr><td colspan="2" style="border-top:1px solid #e5e7eb;padding-top:8px"></td></tr>'
            '<tr style="background:#fde68a"><td style="padding:8px 10px;font-weight:700">Total settlement to close today</td>'
            '<td style="padding:8px 10px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums">₹{}</td></tr>'
            '</table>',
            f'{original:,.2f}', f'{paid_p:,.2f}', f'{outstanding:,.2f}',
            days, months,
            obj.interest_rate_pct,
            'p.m.' if obj.rate_type == obj.RateType.MONTHLY else 'p.a.',
            f'{monthly:,.2f}',
            f'{accrued:,.2f}', f'{paid_i:,.2f}', f'{interest_due:,.2f}',
            f'{total_due:,.2f}',
        )
    balance_summary.short_description = 'Balance summary'

    def loan_no_link(self, obj):
        """Loan # linking to the read-only detail page (not the edit form)."""
        url = reverse('loans:detail', args=[obj.pk])
        return format_html('<a href="{}"><strong>{}</strong></a>',
                           url, obj.loan_no)
    loan_no_link.short_description = 'Loan #'
    loan_no_link.admin_order_field = 'loan_no'

    def tools(self, obj):
        """List-row quick buttons: PDF, WhatsApp."""
        pdf_url = reverse('loans:pledge_ticket', args=[obj.pk])
        wa_url = obj.whatsapp_reminder_link()
        wa = mark_safe('')
        if wa_url:
            wa = format_html(
                '<a href="{}" target="_blank" '
                'style="padding:2px 8px;background:#25D366;color:#fff;'
                'border-radius:4px;text-decoration:none;font-size:11px;'
                'margin-right:4px">WhatsApp</a>', wa_url)
        pdf = format_html(
            '<a href="{}" target="_blank" '
            'style="padding:2px 8px;background:#c46616;color:#fff;'
            'border-radius:4px;text-decoration:none;font-size:11px">PDF</a>',
            pdf_url)
        return format_html('{}{}', wa, pdf)
    tools.short_description = 'Actions'

    def lifecycle_buttons(self, obj):
        if not obj.pk:
            return '—'
        pdf = reverse('loans:pledge_ticket', args=[obj.pk])
        if obj.status in (Loan.Status.CLOSED, Loan.Status.AUCTIONED):
            return format_html(
                '<a href="{}" target="_blank" '
                'style="padding:6px 14px;background:#c46616;color:#fff;'
                'border-radius:6px;text-decoration:none">Print Pledge Ticket</a> '
                '<span style="color:#6b7280;margin-left:8px">'
                'Loan is {} — lifecycle actions disabled.</span>',
                pdf, obj.get_status_display(),
            )
        wa = obj.whatsapp_reminder_link()
        pre = reverse('loans:preclose', args=[obj.pk])
        ren = reverse('loans:renew', args=[obj.pk])
        top = reverse('loans:topup', args=[obj.pk])
        wa_btn = mark_safe('')
        if wa:
            wa_btn = format_html(
                '<a href="{}" target="_blank" '
                'style="padding:6px 14px;background:#25D366;color:#fff;'
                'border-radius:6px;text-decoration:none;'
                'margin-right:6px">Send via WhatsApp</a>', wa)
        return format_html(
            '{}'
            '<a href="{}" target="_blank" style="padding:6px 14px;background:#c46616;color:#fff;border-radius:6px;text-decoration:none;margin-right:6px">Print Pledge Ticket</a>'
            '<a href="{}" style="padding:6px 14px;background:#047857;color:#fff;border-radius:6px;text-decoration:none;margin-right:6px">Top-up</a>'
            '<a href="{}" style="padding:6px 14px;background:#3b82f6;color:#fff;border-radius:6px;text-decoration:none;margin-right:6px">Renew</a>'
            '<a href="{}" style="padding:6px 14px;background:#b91c1c;color:#fff;border-radius:6px;text-decoration:none">Pre-close</a>',
            wa_btn, pdf, top, ren, pre,
        )
    lifecycle_buttons.short_description = 'Actions'

    def ltv_eligible_principal(self, obj):
        """One-line eligibility shown directly above the principal field.

        Wrapped in `#ltv-eligible-principal-live` so the inline JS can update
        it as the user edits gold-item rows (before save).
        """
        if not obj or not obj.pk:
            inner = format_html(
                '<span style="color:#6b7280">Add gold items above — eligible '
                'principal will appear here live.</span>')
        else:
            data = obj.ltv_breakdown()
            if not data['item_breakdown']:
                inner = format_html(
                    '<span style="color:#6b7280">Add gold items above — '
                    'eligible principal will appear here live.</span>')
            else:
                eligible = data['eligible_principal']
                gross = data['gross_value']
                ltv_pct = data['max_ltv_pct']
                current = obj.principal.amount
                ok = current <= eligible
                inner = format_html(
                    '<div style="font-size:13px">'
                    '<span style="font-size:16px;font-weight:700;'
                    'font-variant-numeric:tabular-nums">₹{}</span>'
                    '<span style="color:#6b7280;margin-left:8px">'
                    '= {}% of ₹{} gold value</span>'
                    '<div style="margin-top:4px;padding:4px 10px;'
                    'border-radius:4px;display:inline-block;background:{};'
                    'color:{};font-weight:600;font-size:12px">'
                    'Current principal ₹{} is {} the LTV cap</div>'
                    '</div>',
                    f'{eligible:,.2f}',
                    ltv_pct, f'{gross:,.2f}',
                    '#dcfce7' if ok else '#fee2e2',
                    '#166534' if ok else '#991b1b',
                    f'{current:,.2f}',
                    'within' if ok else 'ABOVE',
                )
        return format_html(
            '<div id="ltv-eligible-principal-live">{}</div>', inner)
    ltv_eligible_principal.short_description = 'LTV-eligible principal'

    def ltv_summary(self, obj):
        # Wrapped in `#ltv-summary-live` so the inline JS can update it.
        if not obj or not obj.pk:
            return format_html(
                '<div id="ltv-summary-live">'
                '<span style="color:#6b7280">Add gold items above — the LTV '
                'breakdown will appear here live (recomputes as you type).'
                '</span></div>')
        data = obj.ltv_breakdown()
        if not data['item_breakdown']:
            return format_html(
                '<div id="ltv-summary-live">'
                '<span style="color:#6b7280">Add gold items above — the LTV '
                'breakdown will appear here live.</span></div>')

        rows_safe = format_html_join(
            '',
            '<tr>'
            '<td style="padding:6px">{}</td>'
            '<td style="padding:6px;text-align:right">{} g</td>'
            '<td style="padding:6px;text-align:right">{} ct</td>'
            '<td style="padding:6px;text-align:right">{}</td>'
            '<td style="padding:6px;text-align:right"><b>₹{}</b></td>'
            '</tr>',
            (
                (
                    r['description'],
                    r['net_wt'],
                    r['purity'],
                    (f'₹{r["rate_per_g"]:.2f}/g' if r['rate_per_g'] else '—'),
                    f'{r["value"]:.2f}',
                )
                for r in data['item_breakdown']
            ),
        )

        ok = obj.principal.amount <= data['eligible_principal']
        verdict_safe = format_html(
            '<div style="margin-top:8px;padding:8px 12px;border-radius:6px;'
            'background:{};color:{};font-weight:600">'
            'Principal ₹{} is {} the LTV cap of ₹{} '
            '({}% of ₹{} gold value).</div>',
            '#dcfce7' if ok else '#fee2e2',
            '#166534' if ok else '#991b1b',
            f'{obj.principal.amount:.2f}',
            'WITHIN' if ok else 'ABOVE',
            f'{data["eligible_principal"]:.2f}',
            data['max_ltv_pct'],
            f'{data["gross_value"]:.2f}',
        )

        warn_safe = mark_safe('')
        if data['warnings']:
            warn_items = format_html_join(
                '<br>', '⚠ {}', ((w,) for w in data['warnings']))
            warn_safe = format_html(
                '<div style="color:#b45309;font-size:12px;margin-top:6px">{}</div>',
                warn_items,
            )

        return format_html(
            '<div id="ltv-summary-live">'
            '<table style="width:100%;border-collapse:collapse;font-size:13px">'
            '<thead><tr style="background:#c46616;color:#fff">'
            '<th style="padding:6px;text-align:left">Item</th>'
            '<th style="padding:6px;text-align:right">Net wt</th>'
            '<th style="padding:6px;text-align:right">Purity</th>'
            '<th style="padding:6px;text-align:right">Rate / g</th>'
            '<th style="padding:6px;text-align:right">Value</th>'
            '</tr></thead><tbody>{}</tbody>'
            '<tfoot>'
            '<tr style="background:#fef3c7">'
            '<td colspan="4" style="padding:6px;text-align:right;font-weight:700">Gross gold value</td>'
            '<td style="padding:6px;text-align:right;font-weight:700">₹{}</td>'
            '</tr>'
            '<tr>'
            '<td colspan="4" style="padding:6px;text-align:right">Max LTV ({}%) → Eligible principal</td>'
            '<td style="padding:6px;text-align:right;font-weight:700">₹{}</td>'
            '</tr>'
            '</tfoot></table>{}{}'
            '</div>',
            rows_safe,
            f'{data["gross_value"]:.2f}',
            data['max_ltv_pct'],
            f'{data["eligible_principal"]:.2f}',
            verdict_safe,
            warn_safe,
        )
    ltv_summary.short_description = 'LTV breakdown'


@admin.register(Repayment)
class RepaymentAdmin(TenantModelAdmin):
    tenant_resource = 'repayment'
    list_display = ('loan', 'paid_at', 'principal_paid', 'interest_paid',
                    'mode', 'receipt_no', 'pdf_link')
    list_filter = ('mode', 'paid_at')
    search_fields = ('loan__loan_no', 'reference', 'receipt_no')
    autocomplete_fields = ['loan']

    class Media:
        # Pre-fill principal_paid / interest_paid from the selected loan's
        # live balance (fetched via loans:balance_json).
        js = ('admin/loans/repayment_autofill.js',)

    def pdf_link(self, obj):
        url = reverse('loans:repayment_receipt', args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" '
            'style="padding:2px 8px;background:#c46616;color:#fff;'
            'border-radius:4px;text-decoration:none;font-size:11px">Receipt</a>',
            url)
    pdf_link.short_description = 'PDF'
