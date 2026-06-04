from django.urls import path
from . import views

app_name = 'signup'

urlpatterns = [
    path('', views.signup_form, name='form'),
    path('sent/', views.signup_sent, name='sent'),
    path('verify/<str:token>/', views.verify_signup, name='verify'),
    path('check-slug/', views.check_slug, name='check_slug'),
]
