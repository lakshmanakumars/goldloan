from django.urls import path
from . import views, actions

app_name = 'loans'

urlpatterns = [
    path('<int:pk>/', views.loan_detail, name='detail'),
    path('api/<int:pk>/balance.json', views.loan_balance_json,
         name='balance_json'),
    path('repayments/<int:pk>/', views.repayment_detail, name='repayment_detail'),
    path('<int:pk>/pledge-ticket.pdf', views.pledge_ticket_pdf,
         name='pledge_ticket'),
    path('repayments/<int:pk>/receipt.pdf', views.repayment_receipt_pdf,
         name='repayment_receipt'),
    # Lifecycle actions
    path('<int:pk>/preclose/', actions.preclose_loan, name='preclose'),
    path('<int:pk>/renew/', actions.renew_loan, name='renew'),
    path('<int:pk>/topup/', actions.topup_loan, name='topup'),
]
