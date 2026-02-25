# src/core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'), # Added Logout Path
    path('demo-login/', views.demo_login_view, name='demo_login'),
    path('resume/', views.resume_view, name='resume'),
    path('resume/edit/', views.edit_resume, name='edit_resume'),
    path('resume/export-pdf/', views.export_resume_pdf, name='export_resume_pdf'),
    
    path('reset-demo/', views.reset_demo_data, name='reset_demo_data'),
]
