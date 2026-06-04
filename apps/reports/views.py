"""Report views.

All views require admin login (is_staff). Tenant-scoped reports additionally
require a current tenant (request.tenant). Super-admin reports require
is_superuser AND the super-admin host (no tenant).
"""
from datetime import date, timedelta
from functools import wraps

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _


def _admin_ctx(request):
    return admin.site.each_context(request)

from apps.core.tenancy import set_current_tenant, clear_current_tenant
from . import services, exports


# ---------- decorators ----------

def tenant_report(view):
    """Require a current tenant + staff."""
    @wraps(view)
    @staff_member_required
    def wrapper(request, *args, **kwargs):
        if request.tenant is None:
            return HttpResponseForbidden(
                'This report is only available inside a tenant portal.')
        # Tenant user must belong to this tenant
        if not request.user.is_superuser and \
                request.user.tenant_id != request.tenant.id:
            return HttpResponseForbidden('Wrong tenant.')
        return view(request, *args, **kwargs)
    return wrapper


def super_report(view):
    """Require super-admin on the super-admin host."""
    @wraps(view)
    @staff_member_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden('Super-admin only.')
        if request.tenant is not None:
            return HttpResponseForbidden(
                'Super-admin reports must be accessed on the platform host '
                '(localhost / admin.*), not a tenant subdomain.')
        return view(request, *args, **kwargs)
    return wrapper


def _parse_date(value, default):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


# ---------- broker reports ----------

@tenant_report
def daily_cash_book(request):
    on_date = _parse_date(request.GET.get('date'), timezone.now().date())
    data = services.daily_cash_book(request.tenant, on_date)

    if request.GET.get('format') == 'xlsx':
        rows = [(r.when, r.kind, r.ref, r.party, r.note,
                 r.amount_out, r.amount_in, r.running) for r in data['rows']]
        return exports.excel_response(
            f'cash-book-{on_date}.xlsx',
            ['Time', 'Direction', 'Ref', 'Party', 'Note',
             'Out (₹)', 'In (₹)', 'Running (₹)'],
            rows, sheet_name=f'CashBook {on_date}',
        )
    return render(request, 'reports/daily_cash_book.html', {
        **_admin_ctx(request),
        'title': _('Daily Cash Book — %(d)s') % {'d': on_date},
        'data': data, 'on_date': on_date,
    })


@tenant_report
def monthly_cash_summary(request):
    year = int(request.GET.get('year') or timezone.now().year)
    data = services.monthly_cash_summary(request.tenant, year)

    if request.GET.get('format') == 'xlsx':
        rows = [(r['month'].strftime('%b %Y'), r['out'], r['in'],
                 r['interest']) for r in data['rows']]
        return exports.excel_response(
            f'monthly-summary-{year}.xlsx',
            ['Month', 'Disbursed (Out)', 'Received (In)', 'Interest Earned'],
            rows, sheet_name=f'Monthly {year}',
        )
    return render(request, 'reports/monthly_cash_summary.html', {
        **_admin_ctx(request),
        'title': _('Monthly Cash Summary — %(y)s') % {'y': year},
        'data': data, 'year': year,
    })


@tenant_report
def outstanding_portfolio(request):
    data = services.outstanding_portfolio(request.tenant)
    if request.GET.get('format') == 'xlsx':
        rows = [(r['loan_no'], r['customer'], r['customer_phone'],
                 r['principal'], r['paid_principal'], r['paid_interest'],
                 r['outstanding'], r['start_date'], r['maturity_date'],
                 r['days_outstanding'], r['status'], r['rate'])
                for r in data['rows']]
        return exports.excel_response(
            'outstanding-portfolio.xlsx',
            ['Loan #', 'Customer', 'Phone', 'Principal', 'Paid Principal',
             'Paid Interest', 'Outstanding', 'Start', 'Maturity',
             'Days', 'Status', 'Rate'],
            rows, sheet_name='Outstanding',
        )
    return render(request, 'reports/outstanding_portfolio.html', {
        **_admin_ctx(request),
        'title': _('Outstanding Loan Portfolio'), 'data': data,
    })


@tenant_report
def interest_earned(request):
    today = timezone.now().date()
    from_date = _parse_date(request.GET.get('from'),
                            today.replace(day=1))
    to_date = _parse_date(request.GET.get('to'), today)
    data = services.interest_earned(request.tenant, from_date, to_date)

    if request.GET.get('format') == 'xlsx':
        rows = [(r['paid_at'], r['loan_no'], r['customer'],
                 r['amount'], r['mode'], r['receipt_no'])
                for r in data['rows']]
        return exports.excel_response(
            f'interest-earned-{from_date}-to-{to_date}.xlsx',
            ['Paid at', 'Loan #', 'Customer', 'Amount', 'Mode', 'Receipt #'],
            rows, sheet_name='Interest Earned',
        )
    return render(request, 'reports/interest_earned.html', {
        **_admin_ctx(request),
        'title': _('Interest Earned — %(f)s to %(t)s')
                  % {'f': from_date, 't': to_date},
        'data': data, 'from_date': from_date, 'to_date': to_date,
    })


@tenant_report
def networth(request):
    kpis = services.compute_kpis(request.tenant)
    nw = services.compute_networth(request.tenant)
    return render(request, 'reports/networth.html', {
        **_admin_ctx(request),
        'title': _('Networth'), 'k': kpis, 'nw': nw,
        'tenant': request.tenant,
    })


@tenant_report
def customer_statement(request, customer_id):
    data = services.customer_statement(request.tenant, customer_id)

    if request.GET.get('format') == 'xlsx':
        rows = [(e['when'], e['event'], e['out'], e['in'], e['balance'])
                for e in data['events']]
        return exports.excel_response(
            f'statement-{data["customer"].code}.xlsx',
            ['Date', 'Event', 'Out', 'In', 'Balance'],
            rows, sheet_name=data['customer'].code,
        )
    return render(request, 'reports/customer_statement.html', {
        **_admin_ctx(request),
        'title': _('Statement — %(name)s') % {'name': data['customer'].name},
        'data': data,
    })


# ---------- super-admin reports ----------

@super_report
def broker_snapshot(request):
    data = services.broker_snapshot()
    if request.GET.get('format') == 'xlsx':
        rows = [(r['tenant'].name, r['tenant'].slug, r['tenant'].status,
                 r['active'], r['overdue'], r['disbursed'], r['received'],
                 r['outstanding'], r['interest_earned'], r['networth'])
                for r in data['rows']]
        return exports.excel_response(
            'broker-snapshot.xlsx',
            ['Broker', 'Slug', 'Status', 'Active', 'Overdue',
             'Lifetime Disbursed', 'Lifetime Received',
             'Outstanding', 'Interest Earned', 'Loan-book Networth'],
            rows, sheet_name='Brokers',
        )
    return render(request, 'reports/broker_snapshot.html', {
        **_admin_ctx(request),
        'title': _('Per-broker Portfolio Snapshot'), 'data': data,
    })


@super_report
def platform_exposure(request):
    kpis = services.compute_kpis(tenant=None)
    return render(request, 'reports/platform_exposure.html', {
        **_admin_ctx(request),
        'title': _('Platform-wide Exposure'), 'k': kpis,
    })
