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

    path('calendar/', views.production_calendar, name='calendar_view'), # 页面
    path('api/events/', views.calendar_events_api, name='api_events'),  # 获取数据
    path('api/event/move/', views.calendar_move_api, name='api_move_event'), # 拖拽更新

    path('<int:pk>/complete-submission/', views.production_complete_submission, name='complete_submission'),

]
