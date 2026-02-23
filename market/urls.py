from django.urls import path

from . import views

urlpatterns = [
    path('ticker/<str:symbol>/', views.ticker_detail, name='ticker_detail'),
    path('news/', views.news_feed_view, name='news_feed'),
    path('settings/', views.settings_view, name='settings'),
    path('api/chart/<str:symbol>/', views.chart_data, name='chart_data'),
    path('api/refresh/<str:symbol>/', views.refresh_ticker_view, name='refresh_ticker'),
    path('api/refresh-all/', views.refresh_all_view, name='refresh_all'),
    path('api/feed/<int:pk>/toggle/', views.toggle_feed_view, name='toggle_feed'),
    path('api/ai-analysis/<str:symbol>/', views.generate_ai_analysis_view, name='generate_ai_analysis'),
]
