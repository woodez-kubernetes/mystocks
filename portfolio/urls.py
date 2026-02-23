from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('metrics/', views.metrics_info, name='metrics_info'),

    # Portfolio CRUD
    path('portfolios/', views.portfolio_list, name='portfolio_list'),
    path('portfolios/create/', views.portfolio_create, name='portfolio_create'),
    path('portfolios/<int:pk>/', views.portfolio_detail, name='portfolio_detail'),
    path('portfolios/<int:pk>/edit/', views.portfolio_edit, name='portfolio_edit'),
    path('portfolios/<int:pk>/delete/', views.portfolio_delete, name='portfolio_delete'),

    # Lot CRUD
    path('portfolios/<int:portfolio_pk>/lots/add/', views.lot_create, name='lot_create'),
    path('lots/<int:pk>/edit/', views.lot_edit, name='lot_edit'),
    path('lots/<int:pk>/delete/', views.lot_delete, name='lot_delete'),

    # API
    path('api/tickers/search/', views.ticker_search, name='ticker_search'),

    # Report
    path('report/send/', views.send_email_report, name='send_email_report'),
    path('report/audit/', views.report_audit_log, name='report_audit_log'),

    # Schedules
    path('report/schedule/add/', views.schedule_create, name='schedule_create'),
    path('report/schedule/<int:pk>/edit/', views.schedule_edit, name='schedule_edit'),
    path('report/schedule/<int:pk>/delete/', views.schedule_delete, name='schedule_delete'),
    path('report/schedule/<int:pk>/toggle/', views.schedule_toggle, name='schedule_toggle'),
]
