from django.urls import path

from analysis import views

urlpatterns = [
    path('opportunities/', views.opportunities_view, name='opportunities'),
    path('opportunities/radar/<str:symbol>/', views.ticker_radar_data, name='radar_data'),
    path('watchlist/', views.watchlist_view, name='watchlist'),
    path('watchlist/add/', views.watchlist_add, name='watchlist_add'),
    path('watchlist/<int:pk>/remove/', views.watchlist_remove, name='watchlist_remove'),
    path('compare/', views.compare_view, name='compare'),
]
