# src/core/views.py
from django.shortcuts import render
from inventory.models import Product

def home(request):
    total_products = Product.objects.count()
    context = {
        'total_products': total_products,
    }

    # 【优化】如果是 AJAX 请求，只返回局部内容
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'core/partials/dashboard_content.html', context)

    # 否则返回包含 Base 的完整页面
    return render(request, 'core/dashboard.html', context)
