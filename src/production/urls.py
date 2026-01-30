from django.urls import path
from . import views

app_name = 'production'

urlpatterns = [
    path('', views.production_dashboard, name='dashboard'),
    path('create/', views.production_create, name='create'),
    path('<int:pk>/', views.production_detail, name='detail'),
    path('<int:pk>/action/<str:action>/', views.production_action, name='action'),

    path('order/<int:pk>/status/', views.production_update_status, name='update_status'),
    path('order/<int:pk>/update/', views.production_update_quantity, name='update_quantity'),

    path('api/max-capacity/', views.get_product_max_capacity, name='get_max_capacity'),
    path('api/calculate-capacity/', views.calculate_production_capacity, name='calculate_capacity'),

    # [NEW] Projected Allocation API
    path('api/projected-allocation/<int:pk>/', views.api_projected_allocation, name='projected_allocation'),

    path('calendar/', views.production_calendar, name='calendar_view'),
    path('api/events/', views.calendar_events_api, name='api_events'),
    path('api/event/move/', views.calendar_move_api, name='api_move_event'),

    path('<int:pk>/complete-submission/', views.production_complete_submission, name='complete_submission'),
]
