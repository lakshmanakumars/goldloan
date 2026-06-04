from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    path('<int:pk>/', views.customer_detail, name='detail'),
]
