from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.core.permissions import role_can, R
from .models import Auction
from .services import build_notice_pdf, total_dues


def _allowed(request, auction):
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant is None or not request.user.is_staff:
        return False
    if auction.tenant_id != tenant.id or request.user.tenant_id != tenant.id:
        return False
    return role_can(request.user, 'auction', R)


@staff_member_required
def auction_detail(request, pk):
    auction = get_object_or_404(Auction.all_objects, pk=pk)
    if not _allowed(request, auction):
        return HttpResponseForbidden('Not allowed.')
    return render(request, 'auctions/detail.html', {
        **admin.site.each_context(request),
        'auction': auction, 'loan': auction.loan,
        'customer': auction.loan.customer,
        'dues': total_dues(auction.loan),
        'items': auction.loan.items.all(),
        'notices': auction.notices.all(),
        'title': f'Auction — {auction.loan.loan_no}',
        'notice1_url': reverse('auctions:send_notice_1', args=[auction.pk]),
        'notice2_url': reverse('auctions:send_notice_2', args=[auction.pk]),
        'schedule_url': reverse('auctions:schedule', args=[auction.pk]),
        'sale_url': reverse('auctions:record_sale', args=[auction.pk]),
        'post_url': reverse('auctions:post_settlement', args=[auction.pk]),
        'cancel_url': reverse('auctions:cancel', args=[auction.pk]),
        'loan_url': reverse('loans:detail', args=[auction.loan.pk]),
        'customer_url': reverse('customers:detail',
                                args=[auction.loan.customer.pk]),
    })


@staff_member_required
def notice_pdf(request, pk, notice_no):
    auction = get_object_or_404(Auction.all_objects, pk=pk)
    if not _allowed(request, auction):
        return HttpResponseForbidden('Not allowed.')
    try:
        notice_no = int(notice_no)
    except ValueError:
        raise Http404
    if notice_no not in (1, 2):
        raise Http404
    pdf = build_notice_pdf(auction, notice_no)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = \
        f'inline; filename="auction-notice-{auction.loan.loan_no}-{notice_no}.pdf"'
    return resp
