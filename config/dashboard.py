"""Unfold admin dashboard callback. Renders KPI cards on the admin home page.

If the request is on a tenant subdomain → broker KPIs for that tenant.
If on the super-admin host  → platform-wide KPIs + per-broker mini list.
"""
from django.urls import reverse
from django.utils.translation import gettext as _
from apps.reports.services import compute_kpis, compute_networth, broker_snapshot


def _money(amount):
    return f'₹{amount:,.2f}'


def dashboard_callback(request, context):
    if request.tenant is not None:
        k = compute_kpis(request.tenant)
        nw = compute_networth(request.tenant)
        context['kpi'] = [
            {'title': _('Outstanding Principal'),
             'metric': _money(k.outstanding_principal),
             'footer': _('%(n)d active loan(s)') % {'n': k.active_loans}},
            {'title': _('Networth'),
             'metric': _money(nw.total_networth),
             'footer': _('Loan book + cash − liabilities')},
            {'title': _('Interest This Month'),
             'metric': _money(k.interest_this_month),
             'footer': _('Cash received as interest (MTD)')},
            {'title': _('Overdue Loans'),
             'metric': str(k.overdue_loans),
             'footer': _('Loans needing attention')},
            {'title': _('Lifetime Disbursed'),
             'metric': _money(k.lifetime_disbursed),
             'footer': _('All loans ever made')},
            {'title': _('Lifetime Interest Earned'),
             'metric': _money(k.lifetime_received_interest),
             'footer': _('Total profit before costs')},
        ]
        context['dashboard_title'] = _('%(name)s — Dashboard') % {
            'name': request.tenant.name}
        context['report_links'] = [
            (_('Daily Cash Book'),  reverse('reports:daily_cash_book')),
            (_('Monthly Summary'),  reverse('reports:monthly_cash_summary')),
            (_('Outstanding Portfolio'),
             reverse('reports:outstanding_portfolio')),
            (_('Interest Earned'),  reverse('reports:interest_earned')),
            (_('Networth'), reverse('reports:networth')),
            (_('Cash Book'), reverse('cashbook:detail')),
        ]
    elif request.user.is_authenticated and request.user.is_superuser:
        k = compute_kpis(tenant=None)
        snap = broker_snapshot()
        context['kpi'] = [
            {'title': _('Brokers Onboarded'),
             'metric': str(len(snap['rows'])),
             'footer': _('Tenants on the platform')},
            {'title': _('Platform Outstanding'),
             'metric': _money(k.outstanding_principal),
             'footer': _('%(n)d active loan(s) across all brokers') % {
                 'n': k.active_loans}},
            {'title': _('Platform Networth (loan-book)'),
             'metric': _money(k.loanbook_networth),
             'footer': _('Sum of all broker loan books')},
            {'title': _('Platform Interest Earned'),
             'metric': _money(k.lifetime_received_interest),
             'footer': _('Lifetime, all brokers')},
            {'title': _('Lifetime Disbursed'),
             'metric': _money(k.lifetime_disbursed),
             'footer': _('Total cash deployed on platform')},
            {'title': _('Overdue Loans'),
             'metric': str(k.overdue_loans),
             'footer': _('Across all brokers')},
        ]
        context['dashboard_title'] = _('Platform Dashboard')
        context['broker_rows'] = snap['rows'][:10]
        context['report_links'] = [
            (_('Per-broker Snapshot'), reverse('reports:broker_snapshot')),
            (_('Platform Exposure'),   reverse('reports:platform_exposure')),
        ]
    return context
