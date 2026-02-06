from django.urls import path
from . import views

app_name = 'forecast'

urlpatterns = [
    path('', views.forecast_dashboard, name='dashboard'),
    path('planning/', views.planning_dashboard, name='planning_dashboard'),
    path('sales-forecast/', views.sales_forecast, name='sales_forecast'),
    path('allocate/<int:pk>/', views.allocate_demand, name='allocate_demand'),
    path('shipment/create/', views.create_shipment, name='create_shipment'),
    path('shipment/<int:pk>/edit/', views.edit_shipment, name='edit_shipment'),
    path('plan/<int:pk>/', views.plan_detail, name='plan_detail'),
    path('plan/<int:pk>/delete/', views.delete_plan, name='delete_plan'),

    path('plan/<int:pk>/refresh/', views.refresh_plan, name='refresh_plan'),
    path('entry/<int:pk>/refresh/', views.refresh_entry, name='refresh_entry'),
]
