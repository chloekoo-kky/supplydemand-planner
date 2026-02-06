from django.urls import path
from . import views

app_name = 'core'
urlpatterns = [
    path('', views.home, name='home'),
    path('portfolio/', views.resume_view, name='resume'),
    path('reset-demo/', views.reset_demo_data, name='reset_demo_data'),

]
