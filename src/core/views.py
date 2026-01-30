# src/core/views.py
from django.shortcuts import render
from inventory.models import Product
from django.db.models import Sum, Count, F, OuterRef, Subquery
from inventory.models import Product, InventorySnapshot
from production.models import ProductionOrder
from forecast.models import MarketDemand
from django.utils import timezone



def home(request):
    # 获取每个产品最新的库存快照
    latest_snapshot = InventorySnapshot.objects.filter(
        product=OuterRef('pk')
    ).order_by('-snapshot_date')

    # 在数据库层面计算当前库存和安全库存阈值
    products_with_stock = Product.objects.annotate(
        current_stock=Subquery(latest_snapshot.values('quantity_on_hand')[:1]),
        calculated_safety_stock=F('estimated_daily_usage') * F('safety_stock_days')
    )

    # 1. 总 SKU 数
    total_products = products_with_stock.count()

    # 2. 低库存预警 (当前库存 < 计算出的安全库存)
    low_stock_products = products_with_stock.filter(current_stock__lt=F('calculated_safety_stock'))
    low_stock_count = low_stock_products.count()

    # 3. 库存总值计算
    total_value = products_with_stock.aggregate(
        total=Sum(F('current_stock') * F('cost_price'))
    )['total'] or 0

    # 4. 获取最近30天的全库库存趋势 (用于图表)
    thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
    history_data = InventorySnapshot.objects.filter(
        snapshot_date__gte=thirty_days_ago
    ).values('snapshot_date').annotate(
        total_qty=Sum('quantity_on_hand')
    ).order_by('snapshot_date')

    context = {
        'total_products': total_products,
        'low_stock_count': low_stock_count,
        'total_inventory_value': f"RM {total_value / 1000000:.2f}M" if total_value >= 1000000 else f"RM {total_value:,.2f}",
        'pending_pos': ProductionOrder.objects.filter(status='PENDING').count(), #
        'urgent_items': low_stock_products[:5], # 仅取前5条显示在侧边栏
        # 传递给前端 Chart.js 的数据
        'chart_labels': [d['snapshot_date'].strftime('%m-%d') for d in history_data],
        'chart_values': [float(d['total_qty']) for d in history_data],
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest': 
        return render(request, 'core/partials/dashboard_content.html', context)

    return render(request, 'core/dashboard.html', context)


def resume_view(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'core/partials/resume_content.html')

    return render(request, 'core/resume.html')

