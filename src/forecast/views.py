from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from collections import defaultdict
from itertools import groupby

from .models import ForecastPlan, MarketDemand, OutboundShipment, ForecastEntry
from inventory.models import Product, InventorySnapshot
from .forms import ImportDemandForm, RunMRPForm
from .services import (
    process_demand_file, run_mrp_engine,
    allocate_stock_for_demand, ship_allocated_demand,
    convert_entries_to_orders, refresh_single_entry_logic
)

def forecast_dashboard(request):
    """
    Refactored Command Center.
    Focuses ONLY on Outbound Queue & Fulfillment.
    """
    # 1. 处理 POST 逻辑 (保持不变)
    if request.method == 'POST':
        if 'ship_item' in request.POST:
            demand_id = request.POST.get('demand_id')
            ship_date_str = request.POST.get('shipment_date')
            if not ship_date_str: ship_date = date.today()
            else: ship_date = date.fromisoformat(ship_date_str)
            success, msg = ship_allocated_demand(demand_id, ship_date)
            if success: messages.success(request, msg)
            else: messages.error(request, msg)
            return redirect('forecast:dashboard')

    # === [关键修改 1] 独立的状态保持逻辑 (Dashboard) ===

    # A. 处理月份 (Month)
    selected_month_str = request.GET.get('month') # 尝试从 URL 获取
    use_date_filter = True

    if selected_month_str is None:
        # 如果 URL 没带参数，尝试读 Dashboard 专属的 Cookie
        selected_month_str = request.COOKIES.get('dashboard_month')

    # 如果读出来是空字符串（用户之前可能点了“全部月份”），则不开启过滤
    if not selected_month_str:
        use_date_filter = False
        selected_month_str = None

    # 解析日期 (保持不变)
    selected_year, selected_month = None, None
    if selected_month_str:
        try:
            selected_year, selected_month = map(int, selected_month_str.split('-'))
        except ValueError:
            use_date_filter = False
            selected_month_str = None

    # B. 处理搜索词 (Query)
    # 逻辑：如果 URL 没有 q 参数，就读 Cookie；如果有，就用新的并准备更新 Cookie
    query = request.GET.get('q')
    if query is None:
        query = request.COOKIES.get('dashboard_query', '')

    query = query.strip().lower()

    # === 业务查询逻辑 (保持不变) ===
    demands_qs = MarketDemand.objects.filter(demand_type='ACTUAL')
    shipments_qs = OutboundShipment.objects.filter(status='PLANNING')

    if use_date_filter:
        demands_qs = demands_qs.filter(
            period_date__year=selected_year,
            period_date__month=selected_month
        )
        shipments_qs = shipments_qs.filter(
            etd__year=selected_year,
            etd__month=selected_month
        )

    target_shipments = shipments_qs.prefetch_related('demands', 'demands__product')
    queue_groups = []

    # Part A: Shipments Filter (应用 query)
    for ship in target_shipments:
        items = list(ship.demands.filter(shipped_date__isnull=True).select_related('product'))

        # 搜索逻辑
        ship_match = True
        if query:
            ship_match = (query in ship.reference.lower()) or \
                         (ship.destination and query in ship.destination.lower())
            if not ship_match:
                items = [
                    i for i in items
                    if (query in i.product.sku.lower()) or (query in i.country.lower())
                ]

        should_show = False
        if query:
            if ship_match or items: should_show = True
        else:
            should_show = True

        if should_show:
            queue_groups.append({
                'shipment': ship,
                'items': items,
                'total_qty': sum(i.allocated_qty for i in items),
                'count': len(items)
            })

    # Part B: Unassigned Items Filter (应用 query)
    unassigned_qs = demands_qs.filter(
        is_allocated=True,
        shipped_date__isnull=True,
        shipment__isnull=True
    ).select_related('product')

    unassigned_items = list(unassigned_qs)

    if query:
        unassigned_items = [
            i for i in unassigned_items
            if (query in i.product.sku.lower()) or (query in i.country.lower())
        ]

    if unassigned_items:
        queue_groups.append({
            'shipment': None,
            'items': unassigned_items,
            'total_qty': sum(i.allocated_qty for i in unassigned_items),
            'count': len(unassigned_items)
        })

    queue_groups.sort(key=lambda x: (x['shipment'].etd if x['shipment'] else date.min))
    active_shipments = OutboundShipment.objects.filter(status='PLANNING').order_by('etd')

    context = {
        'current_month': selected_month_str,
        'current_query': query,
        'queue_groups': queue_groups,
        'active_shipments': active_shipments,
        'today_date': date.today().isoformat()
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        response = render(request, 'forecast/partials/fulfillment_content.html', context)
    else:
        response = render(request, 'forecast/forecast_dashboard.html', context)

    # === [关键修改 2] 写入 Dashboard 专属 Cookie ===
    # 只有当 URL 中显式传递了参数时，才更新 Cookie
    if request.GET.get('month') is not None:
        response.set_cookie('dashboard_month', request.GET.get('month'))

    if request.GET.get('q') is not None:
        response.set_cookie('dashboard_query', request.GET.get('q'))

    return response


def planning_dashboard(request):
    """
    [NEW] Dedicated page for MRP Engine and Forecast Plans.
    """
    if request.method == 'POST' and 'run_mrp' in request.POST:
        form = RunMRPForm(request.POST)
        if form.is_valid():
            success, msg = run_mrp_engine(form.cleaned_data['target_month'])
            if success: messages.success(request, msg)
            else: messages.warning(request, msg)
        else:
            messages.error(request, f"MRP Launch Failed: {form.errors}")
        return redirect('forecast:planning_dashboard')

    plans = ForecastPlan.objects.all().order_by('-created_at')
    mrp_initial_date = date.today().replace(day=1)

    context = {
        'plans': plans,
        'mrp_form': RunMRPForm(initial={'target_month': mrp_initial_date}),
        'total_plans': plans.count(),
    }

    # Check if request is AJAX
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'forecast/partials/planning_dashboard_content.html', context)

    # For direct browser refresh, you might need a separate wrapper template
    # or keep the extends and use a variable to toggle it.
    return render(request, 'forecast/planning_dashboard.html', context)


@require_POST
def create_shipment(request):
    ref = request.POST.get('reference')
    etd = request.POST.get('etd')
    dest = request.POST.get('destination', '').strip()

    if ref and etd:
        try:
            OutboundShipment.objects.create(reference=ref, etd=etd, destination=dest)
            messages.success(request, f"Shipment {ref} created.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return redirect('forecast:dashboard')


@require_POST
def edit_shipment(request, pk):
    shipment = get_object_or_404(OutboundShipment, pk=pk)
    new_ref = request.POST.get('reference')
    new_etd = request.POST.get('etd')
    new_dest = request.POST.get('destination', '').strip()

    if new_ref and new_etd:
        try:
            if new_dest and shipment.demands.exists():
                conflicts = shipment.demands.exclude(country__iexact=new_dest)
                if conflicts.exists():
                    conflict_names = list(set(conflicts.values_list('country', flat=True)))
                    messages.error(request, f"Cannot change destination to '{new_dest}'. Container already holds items for: {', '.join(conflict_names)}.")
                    return redirect('forecast:dashboard')

            shipment.reference = new_ref
            shipment.etd = new_etd
            shipment.destination = new_dest
            shipment.save()
            messages.success(request, f"Shipment updated.")
        except Exception as e:
            messages.error(request, f"Error updating shipment: {str(e)}")

    return redirect('forecast:dashboard')


def sales_forecast(request):
    """
    Unified View with Dynamic KPIs based on filtered results and Pagination.
    """
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

    # 1. Fetch ALL Data
    raw_demands = MarketDemand.objects.select_related('product').all().order_by('period_date', 'country', 'product__sku')

    # 2. Merge Data
    merged_data_by_country = defaultdict(lambda: {
        'period': None, 'country': None, 'product': None,
        'forecast_qty': 0, 'actual_qty': 0, 'actual_obj': None
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

    # 3. Group by Product & Period
    grouped_map = defaultdict(lambda: {
        'period': None, 'product': None,
        'total_forecast': 0, 'total_actual': 0, 'total_allocated': 0,
        'total_gap': 0, 'achievement_rate': 0,
        'details': []
    })

    for item in merged_data_by_country.values():
        group_key = (item['period'], item['product'].id)
        group = grouped_map[group_key]
        if not group['product']:
            group['period'] = item['period']
            group['product'] = item['product']
        group['total_forecast'] += item['forecast_qty']
        group['total_actual'] += item['actual_qty']
        if item['actual_obj']:
            group['total_allocated'] += item['actual_obj'].allocated_qty
        group['details'].append(item)

    for group in grouped_map.values():
        group['total_gap'] = group['total_actual'] - group['total_allocated']
        if group['total_forecast'] > 0:
            group['achievement_rate'] = (group['total_actual'] / group['total_forecast']) * 100
        else:
            group['achievement_rate'] = 0

    grouped_list = list(grouped_map.values())

    # 4. Filter by Month
    selected_month = request.GET.get('month')
    if selected_month is None:
        # 读取 Sales Forecast 专属 Cookie
        selected_month = request.COOKIES.get('sales_forecast_month')

    if selected_month is None: selected_month = ''
    selected_month = selected_month.strip()

    if selected_month and selected_month.upper() != 'ALL':
        filtered_by_month = []
        for group in grouped_list:
            if group['period'].strftime('%Y-%m') == selected_month:
                filtered_by_month.append(group)
        grouped_list = filtered_by_month

    # 5. Filter by Search
    query = request.GET.get('q')
    if query is None:
        # 读取 Sales Forecast 专属 Query Cookie
        query = request.COOKIES.get('sales_forecast_query', '')

    query = query.strip().lower()

    if query:
        filtered_list = []
        for group in grouped_list:
            match_product = (query in group['product'].sku.lower()) or (query in group['product'].description.lower())
            match_country = any(query in d['country'].lower() for d in group['details'])
            if match_product or match_country:
                filtered_list.append(group)
        grouped_list = filtered_list

    # === KPIs ===
    kpi_total_orders = 0
    kpi_allocated_pending = 0
    kpi_shipped = 0

    for group in grouped_list:
        kpi_total_orders += group['total_actual']
        kpi_allocated_pending += group['total_allocated']
        for detail in group['details']:
            if detail['actual_obj'] and detail['actual_obj'].shipped_date:
                kpi_shipped += detail['actual_qty']

    if kpi_total_orders > 0:
        kpi_fulfillment_rate = (kpi_shipped / kpi_total_orders) * 100
    else:
        kpi_fulfillment_rate = 0

    # 6. Sorting
    sort_by = request.GET.get('sort', 'date_asc')
    # ... (Sort logic omitted for brevity but assumed present in your file, ensure it matches original) ...
    # [Restoring sort logic block to be safe]
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
    elif sort_by == 'forecast_desc':
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
    elif sort_by == 'rate_desc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['achievement_rate'], reverse=True)
    elif sort_by == 'rate_asc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['achievement_rate'])
    elif sort_by == 'allocated_desc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_allocated'], reverse=True)
    elif sort_by == 'allocated_asc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_allocated'])
    elif sort_by == 'gap_desc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_gap'], reverse=True)
    elif sort_by == 'gap_asc':
        grouped_list.sort(key=lambda x: x['period'], reverse=True)
        grouped_list.sort(key=lambda x: x['total_gap'])

    for group in grouped_list:
        group['details'].sort(key=lambda x: x['country'])

    # 7. Pagination
    paginator = Paginator(grouped_list, 10)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # 8. Calculate Inventory Availability
    if page_obj:
        product_ids = set(g['product'].id for g in page_obj)
        snapshots = InventorySnapshot.objects.filter(product_id__in=product_ids).order_by('product_id', '-snapshot_date')
        stock_map = {}
        for s in snapshots:
            if s.product_id not in stock_map:
                stock_map[s.product_id] = s.quantity_on_hand - s.quantity_reserved

        for group in page_obj:
            pid = group['product'].id
            group['available_stock'] = stock_map.get(pid, 0)

    active_shipments = OutboundShipment.objects.filter(status='PLANNING').order_by('etd')

    context = {
        'grouped_demands': page_obj,
        'import_form': ImportDemandForm(),
        'current_sort': sort_by,
        'current_query': request.GET.get('q', ''),
        'current_month_filter': selected_month,
        'active_shipments': active_shipments,
        'kpi_total_orders': kpi_total_orders,
        'kpi_allocated_pending': kpi_allocated_pending,
        'kpi_shipped': kpi_shipped,
        'kpi_fulfillment_rate': kpi_fulfillment_rate,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        response = render(request, 'forecast/partials/sales_forecast_content.html', context)
    else:
        response = render(request, 'forecast/sales_forecast.html', context)

    # === [关键修改 4] 写入 Sales Forecast 专属 Cookie ===
    if request.GET.get('month') is not None:
        response.set_cookie('sales_forecast_month', request.GET.get('month'))

    if request.GET.get('q') is not None:
        response.set_cookie('sales_forecast_query', request.GET.get('q'))

    return response

@require_POST
def allocate_demand(request, pk):
    allocate_qty = request.POST.get('allocate_qty')
    shipment_id = request.POST.get('shipment_id')

    if allocate_qty is None:
        messages.error(request, "Missing quantity.")
        return redirect('forecast:sales_forecast')

    if not shipment_id: shipment_id = None
    success, msg = allocate_stock_for_demand(pk, allocate_qty, shipment_id)

    if success: messages.success(request, msg)
    else: messages.error(request, msg)

    return redirect('forecast:sales_forecast')

def plan_detail(request, pk):
    plan = get_object_or_404(ForecastPlan, pk=pk)
    if request.method == 'POST':
        selected_ids = request.POST.getlist('selected_entries')
        if selected_ids:
            count = convert_entries_to_orders(selected_ids)
            if count > 0:
                messages.success(request, f"Successfully created {count} production orders.")
                if not plan.entries.filter(production_order__isnull=True).exists():
                    plan.is_locked = True
                    plan.save()
            else:
                messages.warning(request, "No orders created (items might be already converted).")
        else:
            messages.warning(request, "Please select items to convert.")
        return redirect('forecast:plan_detail', pk=pk)

    return render(request, 'forecast/plan_detail.html', {'plan': plan})


def delete_plan(request, pk):
    plan = get_object_or_404(ForecastPlan, pk=pk)
    plan.delete()
    messages.success(request, "Plan deleted.")
    return redirect('forecast:dashboard')

def refresh_plan(request, pk):
    """
    Regenerates the entire plan for the specific month.
    """
    plan = get_object_or_404(ForecastPlan, pk=pk)
    target_month = plan.target_month

    # This will delete the current plan object and create a new one
    success, msg = run_mrp_engine(target_month)

    if success:
        messages.success(request, f"Plan for {target_month:%b %Y} refreshed successfully.")
    else:
        messages.error(request, msg)

    return redirect('forecast:planning_dashboard')

def refresh_entry(request, pk):
    """
    Recalculates MRP for a specific entry row.
    """
    success, msg = refresh_single_entry_logic(pk)

    # We need to find the plan PK to redirect back.
    # Since entry might be saved, we can get it from the entry object in DB or before call
    # Logic: refresh_single_entry_logic updates the object in place, so the ID is valid.
    entry = get_object_or_404(ForecastEntry, pk=pk)

    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    return redirect('forecast:plan_detail', pk=entry.plan.pk)
