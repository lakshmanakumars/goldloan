from django.contrib import admin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter, RangeNumericFilter)
from apps.core.admin import TenantModelAdmin
from apps.core.filters import FlatpickrRangeDateFilter
from .models import GoldRate


@admin.register(GoldRate)
class GoldRateAdmin(TenantModelAdmin):
    tenant_resource = 'rate'
    list_display = ('rate_date', 'purity_carat', 'rate_per_gram',
                    'source', 'note', 'created_at')
    list_filter = (
        ('rate_date', FlatpickrRangeDateFilter),
        ('source', ChoicesDropdownFilter),
        ('purity_carat', RangeNumericFilter),
    )
    search_fields = ('note',)
    date_hierarchy = 'rate_date'
    fields = ('rate_date', 'purity_carat', 'rate_per_gram', 'source', 'note')
