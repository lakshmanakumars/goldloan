from django.contrib import admin
from apps.core.admin import TenantModelAdmin
from .models import GoldRate


@admin.register(GoldRate)
class GoldRateAdmin(TenantModelAdmin):
    tenant_resource = 'rate'
    list_display = ('rate_date', 'purity_carat', 'rate_per_gram',
                    'source', 'note', 'created_at')
    list_filter = ('purity_carat', 'source', 'rate_date')
    search_fields = ('note',)
    date_hierarchy = 'rate_date'
    fields = ('rate_date', 'purity_carat', 'rate_per_gram', 'source', 'note')
