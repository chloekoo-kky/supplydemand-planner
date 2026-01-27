from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from django.views.decorators.http import require_POST
from collections import defaultdict

from .models import ForecastPlan, MarketDemand
from inventory.models import Product, InventorySnapshot
from .forms import ImportDemandForm, RunMRPForm
from .services import (
    process_demand_file, run_mrp_engine,
    create_po_from_plan, allocate_stock_for_demand,
    ship_allocated_demand
)

def forecast_dashboard(request):
    """
    Refactored Command Center: Forecast KPIs + Outbound Control.
    """
    # 1. Handle Actions (Run MRP or Ship Items)
    if request.method == 'POST':
        if 'run_mrp' in request.POST:
            form = RunMRPForm(request.POST)
            if form.is_valid():
                success, msg = run_mrp_engine(form.cleaned_data['target_month'])
                if success: messages.success(request, msg)
                else: messages.warning(request, msg)
            return redirect('forecast:dashboard')

        elif 'ship_item' in request.POST: # [新增] 处理出货
            demand_id = request.POST.get('demand_id')
            ship_date_str = request.POST.get('shipment_date')

            if not ship_date_str:
                ship_date = date.today()
            else:
                ship_date = date.fromisoformat(ship_date_str)

            success, msg = ship_allocated_demand(demand_id, ship_date)
            if success: messages.success(request, msg)
            else: messages.error(request, msg)
            return redirect('forecast:dashboard')

    # 2. Forecast / MRP Data
    plans = ForecastPlan.objects.all().order_by('-created_at')
    total_plans = plans.count()
    latest_plan = plans.first()

    next_month = timezone.now().replace(day=1)
    total_demand_next_month = MarketDemand.objects.filter(
        demand_type='FORECAST',
        period_date__gte=next_month
    ).aggregate(Sum('quantity'))['quantity__sum'] or 0

    # 3. [新增] Allocation & Outbound Data
    # 获取所有 "已分配但未出货" 的 items
    allocated_demands = MarketDemand.objects.filter(
        demand_type='ACTUAL',
        is_allocated=True,
        shipped_date__isnull=True
    ).select_related('product').order_by('period_date')

    total_allocated_qty = allocated_demands.aggregate(Sum('quantity'))['quantity__sum'] or 0

    # 统计本月已出货数量 (作为成就展示)
    current_month_start = date.today().replace(day=1)
    shipped_this_month = MarketDemand.objects.filter(
        shipped_date__gte=current_month_start
    ).aggregate(Sum('quantity'))['quantity__sum'] or 0

    context = {
        'plans': plans,
        'mrp_form': RunMRPForm(),
        'total_plans': total_plans,
        'latest_plan_date': latest_plan.created_at if latest_plan else None,
        'demand_kpi': total_demand_next_month,

        # New Context
        'allocated_demands': allocated_demands,
        'total_allocated_qty': total_allocated_qty,
        'shipped_this_month': shipped_this_month,
        'today_date': date.today().isoformat()
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'forecast/partials/dashboard_content.html', context)

    return render(request, 'forecast/forecast_dashboard.html', context)


def sales_forecast(request):
    """
    Unified View: Merges Forecast and Actuals into a single table.
    Refactored to group by Period + Product.
    """
    # 1. Handle Import (保持不变)
    if request.method == 'POST' and 'import_demand' in request.POST:
        form = ImportDemandForm(request.POST, request.FILES)
        if form.is_valid():
            success, msg = process_demand_file(
                form.cleaned_data['file'],
                form.cleaned_data['country'],
                form.cleaned_data['demand_type']
            )
            if success: messages.success(request, msg)
            else: messages.error(request, str(msg))
            return redirect('forecast:sales_forecast')

    # 2. Fetch ALL Data
    raw_demands = MarketDemand.objects.select_related('product').all().order_by('-period_date', 'country', 'product__sku')

    # 3. First Merge: Ensure Forecast and Actuals for the SAME (Period, Country, Product) are in one dict
    # (这一步是为了把同一个国家同一产品的 预测和实销 对齐)
    merged_data_by_country = defaultdict(lambda: {
        'period': None,
        'country': None,
        'product': None,
        'forecast_qty': 0,
        'actual_qty': 0,
        'actual_obj': None
    })

    for d in raw_demands:
        key = (d.period_date, d.country, d.product_id)
        entry = merged_data_by_country[key]

        if not entry['product']:
            entry['period'] = d.period_date
            entry['country'] = d.country
            entry['product'] = d.product

        if d.demand_type == 'FORECAST':
            entry['forecast_qty'] = d.quantity
        elif d.demand_type == 'ACTUAL':
            entry['actual_qty'] = d.quantity
            entry['actual_obj'] = d

    # 4. Second Grouping: Group by (Period, Product) for the Accordion View
    # (这一步是新增的：把不同国家的明细归纳到同一个产品下)
    grouped_map = defaultdict(lambda: {
        'period': None,
        'product': None,
        'total_forecast': 0,
        'total_actual': 0,
        'details': [] # 存放各个国家的明细 list
    })

    for item in merged_data_by_country.values():
        # item 是某个国家的数据
        group_key = (item['period'], item['product'].id)
        group = grouped_map[group_key]

        if not group['product']:
            group['period'] = item['period']
            group['product'] = item['product']

        # 累加总数
        group['total_forecast'] += item['forecast_qty']
        group['total_actual'] += item['actual_qty']

        # 将明细加入列表
        group['details'].append(item)

    grouped_list = list(grouped_map.values())

    # Search Filter
    query = request.GET.get('q', '').strip().lower()
    if query:
        filtered_list = []
        for group in grouped_list:
            # 搜索匹配逻辑：匹配 SKU 或 产品名 或 任意子行中的国家名
            match_product = (query in group['product'].sku.lower()) or (query in group['product'].description.lower())
            match_country = any(query in d['country'].lower() for d in group['details'])

            if match_product or match_country:
                filtered_list.append(group)
        grouped_list = filtered_list

    # 5.2 Sorting
    # 默认按日期倒序
    sort_by = request.GET.get('sort', 'date_desc')

    # 辅助排序 Key
    if sort_by == 'date_desc':
        grouped_list.sort(key=lambda x: x['product'].sku)
        grouped_list.sort(key=lambda x: x['period'], reverse=True)

    elif sort_by == 'date_asc':
        grouped_list.sort(key=lambda x: x['product'].sku)
        grouped_list.sort(key=lambda x: x['period'])

    elif sort_by == 'sku_asc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['product'].sku)

    elif sort_by == 'sku_desc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['product'].sku, reverse=True)

    # --- [新增] Forecast & Actual Sorting ---
    elif sort_by == 'forecast_desc':
        # 按预测量从大到小 (次要排序可以用 Period)
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_forecast'], reverse=True)

    elif sort_by == 'forecast_asc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_forecast'])

    elif sort_by == 'actual_desc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_actual'], reverse=True)

    elif sort_by == 'actual_asc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_actual'])

    # 对每个组内的 details 始终按国家名排序
    for group in grouped_list:
        group['details'].sort(key=lambda x: x['country'])

    if grouped_list:
        product_ids = set(g['product'].id for g in grouped_list)

        # 获取相关产品的 Snapshot，按日期倒序
        snapshots = InventorySnapshot.objects.filter(
            product_id__in=product_ids
        ).order_by('product_id', '-snapshot_date')

        # 在 Python 中提取每个产品的最新一条记录 (兼容所有数据库)
        stock_map = {}
        for s in snapshots:
            if s.product_id not in stock_map:
                # 这是一个产品的最新 snapshot
                # Net Available = On Hand - Reserved
                stock_map[s.product_id] = s.quantity_on_hand - s.quantity_reserved

        # 将库存数据附带到 group 对象上
        for group in grouped_list:
            pid = group['product'].id
            # 如果没有 snapshot，默认为 0
            group['available_stock'] = stock_map.get(pid, 0)

    context = {
        'grouped_demands': grouped_list,
        'import_form': ImportDemandForm(),
        'current_sort': sort_by,    # 回传给前端用于高亮表头
        'current_query': request.GET.get('q', ''), # 回传给前端用于填充搜索框
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'forecast/partials/sales_forecast_content.html', context)

    return render(request, 'forecast/sales_forecast.html', context)



@require_POST
def allocate_demand(request, pk):
    """
    Updated to accept 'allocate_qty' from Modal Form.
    """
    allocate_qty = request.POST.get('allocate_qty')

    if allocate_qty is None:
        messages.error(request, "Missing quantity.")
        return redirect('forecast:sales_forecast')

    success, msg = allocate_stock_for_demand(pk, allocate_qty)

    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    return redirect('forecast:sales_forecast')


def plan_detail(request, pk):
    plan = get_object_or_404(ForecastPlan, pk=pk)

    if request.method == 'POST' and 'convert_po' in request.POST:
        msg = create_po_from_plan(pk)
        messages.success(request, msg)
        return redirect('forecast:plan_detail', pk=pk)

    return render(request, 'forecast/plan_detail.html', {'plan': plan})

def delete_plan(request, pk):
    plan = get_object_or_404(ForecastPlan, pk=pk)
    plan.delete()
    messages.success(request, "Plan deleted.")
    return redirect('forecast:dashboard')
