from django.urls import path

from apps.core import views

app_name = 'core'

urlpatterns = [
    path('theme.css', views.theme_css, name='theme_css'),
]
