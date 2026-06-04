from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # broker (tenant)
    path('daily-cash-book/', views.daily_cash_book, name='daily_cash_book'),
    path('monthly-summary/', views.monthly_cash_summary, name='monthly_cash_summary'),
    path('outstanding/', views.outstanding_portfolio, name='outstanding_portfolio'),
    path('interest-earned/', views.interest_earned, name='interest_earned'),
    path('networth/', views.networth, name='networth'),
    path('customer/<int:customer_id>/statement/',
         views.customer_statement, name='customer_statement'),

    # super-admin
    path('super/broker-snapshot/', views.broker_snapshot, name='broker_snapshot'),
    path('super/platform-exposure/', views.platform_exposure, name='platform_exposure'),
]
