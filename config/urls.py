from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.core.views import home

urlpatterns = [
    path('', home, name='home'),
    path('', include('apps.core.urls', namespace='core')),  # /theme.css
    path('signup/', include('apps.signup.urls', namespace='signup')),
    path('i18n/', include('django.conf.urls.i18n')),  # set_language view
    path('admin/reports/', include('apps.reports.urls', namespace='reports')),
    path('admin/loans/', include('apps.loans.urls', namespace='loans')),
    path('admin/customers/', include('apps.customers.urls', namespace='customers')),
    path('admin/cashbook/', include('apps.cashbook.urls', namespace='cashbook')),
    path('admin/auctions/', include('apps.auctions.urls', namespace='auctions')),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
