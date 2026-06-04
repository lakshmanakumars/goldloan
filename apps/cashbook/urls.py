from django.urls import path
from . import views

app_name = 'cashbook'

urlpatterns = [
    path('', views.cash_book_detail, name='detail'),
    path('day-close/', views.day_close_form, name='day_close'),
]
