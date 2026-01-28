from django.urls import path
from . import views

app_name = 'forecast'

urlpatterns = [
    path('', views.forecast_dashboard, name='dashboard'),
    path('sales-forecast/', views.sales_forecast, name='sales_forecast'),
    path('allocate/<int:pk>/', views.allocate_demand, name='allocate_demand'),
    path('shipment/create/', views.create_shipment, name='create_shipment'),
    path('shipment/<int:pk>/edit/', views.edit_shipment, name='edit_shipment'), # [New]
    path('plan/<int:pk>/', views.plan_detail, name='plan_detail'),
    path('plan/<int:pk>/delete/', views.delete_plan, name='delete_plan'),
]
