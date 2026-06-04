from django.urls import path
from . import views, actions

app_name = 'auctions'

urlpatterns = [
    path('<int:pk>/', views.auction_detail, name='detail'),
    path('<int:pk>/notice/<int:notice_no>.pdf', views.notice_pdf,
         name='notice_pdf'),

    # Lifecycle
    path('<int:pk>/notice-1/', actions.send_notice_1, name='send_notice_1'),
    path('<int:pk>/notice-2/', actions.send_notice_2, name='send_notice_2'),
    path('<int:pk>/schedule/', actions.schedule_auction, name='schedule'),
    path('<int:pk>/sale/', actions.record_sale, name='record_sale'),
    path('<int:pk>/post/', actions.post_settlement, name='post_settlement'),
    path('<int:pk>/cancel/', actions.cancel_auction, name='cancel'),
]
