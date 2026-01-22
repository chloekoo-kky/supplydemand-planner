from django.urls import path
from . import views

app_name = 'production'

urlpatterns = [
    path('', views.production_dashboard, name='dashboard'),
    path('create/', views.production_create, name='create'),
    path('<int:pk>/', views.production_detail, name='detail'),
    path('<int:pk>/action/<str:action>/', views.production_action, name='action'),
    path('api/max-capacity/', views.get_product_max_capacity, name='get_max_capacity'),
    path('api/calculate-capacity/', views.calculate_production_capacity, name='calculate_capacity'),
    path('order/<int:pk>/update/', views.production_update_quantity, name='update_quantity'),


]
