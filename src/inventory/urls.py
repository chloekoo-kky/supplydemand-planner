from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # 核心列表页面 (例如: /inventory/type/RAW/)
    path('type/<str:nature_code>/', views.inventory_list, name='inventory_list_by_nature'),

    # 兼容旧路由 (默认去 RAW)
    path('', views.inventory_list, {'nature_code': 'RAW'}, name='inventory_list'),

    # API Endpoints
    path('api/group/create/', views.group_create, name='group_create'),
    path('api/group/rename/<int:group_id>/', views.group_rename, name='group_rename'),
    path('api/group/delete/<int:group_id>/', views.group_delete, name='group_delete'),
    path('api/product/move/<int:product_id>/', views.product_move, name='product_move'),
    path('api/product/delete/<int:product_id>/', views.product_delete, name='product_delete'),
    path('api/product/reorder/', views.product_reorder, name='product_reorder'),

    # Import 保持不变
    path('import/load/', views.load_import_modal, name='import_load'),
    path('import/process/', views.process_import_file, name='import_process'),
    path('import/finalize/', views.finalize_import, name='import_finalize'),
    path('import/template/', views.download_import_template, name='import_template'),
    
    path('product/update/<int:pk>/', views.product_update, name='product_update'),

    path('api/category/rename/', views.category_rename, name='category_rename'),
    path('api/category/delete/', views.category_delete, name='category_delete'),

    # BOM (Recipe) Management
    path('api/bom/list/<int:product_id>/', views.bom_list, name='bom_list'),
    path('api/bom/add/', views.bom_add, name='bom_add'),
    path('api/bom/update/<int:bom_id>/', views.bom_update, name='bom_update'),
    path('api/bom/delete/<int:bom_id>/', views.bom_delete, name='bom_delete'),
    path('api/product/search-components/', views.product_search_components, name='product_search_components'),

]
