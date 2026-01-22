from django.contrib import admin
from django.urls import path, include

# ==============================================================================
# 自定义 Admin 侧边栏排序逻辑 (Monkey Patch)
# ==============================================================================
def get_custom_app_list(self, request, app_label=None):
    """
    拦截 Django Admin 的 get_app_list 方法，强制按照我们想要的顺序排列。
    """
    # 1. 获取原始的 app_list (即 Django 默认生成的无序/字母序列表)
    # 这里的 self 指向 admin.site 实例
    app_list = admin.AdminSite.get_app_list(self, request, app_label)

    # 2. 定义我们想要的顺序配置
    # 格式: 'app_label': ['ModelName1', 'ModelName2', ...]
    ORDER_CONFIG = {
        'inventory': [
            'Product',             # 1. 总表
            'RawMaterial',         # 2. 原料
            'PackagingMaterial',   # 3. 包材
            'FinishedGoods',       # 4. 成品
            'InventorySnapshot',   # 5. 库存快照
        ],
        'auth': [
            'Group',
            'User'
        ]
        # 'core' 里的模型如果没有特定顺序，可以不写，它们会按默认显示
    }

    # APP 的显示顺序
    APP_ORDER = ['core', 'inventory', 'auth']

    # --- 核心排序算法 ---
    new_app_list = []

    # 为了方便查找，先把 app_list 转成字典: {'inventory': app_dict, ...}
    app_dict_map = {app['app_label']: app for app in app_list}

    # A. 按照 APP_ORDER 重组 App 列表
    for label in APP_ORDER:
        if label in app_dict_map:
            app = app_dict_map[label]

            # B. 如果这个 App 配置了模型顺序，则在内部进行模型排序
            if label in ORDER_CONFIG:
                custom_models = ORDER_CONFIG[label]
                # 建立模型映射: {'Product': model_dict}
                model_map = {m['object_name']: m for m in app['models']}

                sorted_models = []
                # 1. 先加配置好的
                for model_name in custom_models:
                    if model_name in model_map:
                        sorted_models.append(model_map[model_name])

                # 2. 再加没配置的 (防止有新模型被遗漏)
                for m in app['models']:
                    if m['object_name'] not in custom_models:
                        sorted_models.append(m)

                app['models'] = sorted_models

            new_app_list.append(app)

    # C. 把剩下的 App (未在 APP_ORDER 定义的) 追加到最后
    for app in app_list:
        if app['app_label'] not in APP_ORDER:
            new_app_list.append(app)

    return new_app_list

# 将自定义方法绑定到 admin.site 实例上，替换原有的方法
admin.site.get_app_list = get_custom_app_list.__get__(admin.site, admin.AdminSite)

# ==============================================================================
# URL Patterns
# ==============================================================================

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('inventory/', include('inventory.urls')),
    path('production/', include('production.urls')),
    
]
