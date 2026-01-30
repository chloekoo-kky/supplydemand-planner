from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from django.views.decorators.http import require_POST
from collections import defaultdict
from itertools import groupby

from .models import ForecastPlan, MarketDemand, OutboundShipment, ForecastEntry
from inventory.models import Product, InventorySnapshot
from .forms import ImportDemandForm, RunMRPForm
from .services import (
    process_demand_file, run_mrp_engine,
    create_po_from_plan, allocate_stock_for_demand,
    ship_allocated_demand, convert_entries_to_orders
)

def forecast_dashboard(request):
    """
    Refactored Command Center.
    KPIs moved to Sales Forecast. This view now focuses on Outbound Queue & MRP.
    """
    if request.method == 'POST':
        if 'run_mrp' in request.POST:
            form = RunMRPForm(request.POST)
            if form.is_valid():
                success, msg = run_mrp_engine(form.cleaned_data['target_month'])
                if success: messages.success(request, msg)
                else: messages.warning(request, msg)
            else:
                # [新增] 如果校验失败，告诉用户原因
                messages.error(request, f"MRP 启动失败: {form.errors}")
            return redirect('forecast:dashboard')
        
        elif 'ship_item' in request.POST:
            demand_id = request.POST.get('demand_id')
            ship_date_str = request.POST.get('shipment_date')
            if not ship_date_str: ship_date = date.today()
            else: ship_date = date.fromisoformat(ship_date_str)
            success, msg = ship_allocated_demand(demand_id, ship_date)
            if success: messages.success(request, msg)
            else: messages.error(request, msg)
            return redirect('forecast:dashboard')

    # Filter Logic (Still needed for Queue filtering)
    selected_month_str = request.GET.get('month')
    if not selected_month_str:
        selected_month_str = request.COOKIES.get('forecast_dashboard_month')
    try:
        if not selected_month_str: raise ValueError
        selected_year, selected_month = map(int, selected_month_str.split('-'))
    except:
        filter_date = date.today().replace(day=1)
        selected_month_str = filter_date.strftime('%Y-%m')
        selected_year = filter_date.year
        selected_month = filter_date.month

    # === Outbound Queue Logic ===
    month_demands = MarketDemand.objects.filter(
        demand_type='ACTUAL',
        period_date__year=selected_year,
        period_date__month=selected_month
    )

    # 1. Fetch relevant shipments
    target_shipments = OutboundShipment.objects.filter(
        status='PLANNING',
        etd__year=selected_year,
        etd__month=selected_month
    ).prefetch_related('demands', 'demands__product')

    queue_groups = []

    # Part A: Shipments for this month
    for ship in target_shipments:
        items = list(ship.demands.filter(shipped_date__isnull=True).select_related('product'))
        queue_groups.append({
            'shipment': ship,
            'items': items,
            'total_qty': sum(i.allocated_qty for i in items),
            'count': len(items)
        })

    # Part B: Unassigned Items
    unassigned_items = list(month_demands.filter(
        is_allocated=True,
        shipped_date__isnull=True,
        shipment__isnull=True
    ).select_related('product'))

    if unassigned_items:
        queue_groups.append({
            'shipment': None,
            'items': unassigned_items,
            'total_qty': sum(i.allocated_qty for i in unassigned_items),
            'count': len(unassigned_items)
        })

    queue_groups.sort(key=lambda x: (x['shipment'].etd if x['shipment'] else date.min))

    active_shipments = OutboundShipment.objects.filter(status='PLANNING').order_by('etd')
    plans = ForecastPlan.objects.all().order_by('-created_at')

    context = {
        'plans': plans,
        'mrp_form': RunMRPForm(),
        'total_plans': plans.count(),
        'current_month': selected_month_str,
        'queue_groups': queue_groups,
        'active_shipments': active_shipments,
        'today_date': date.today().isoformat()
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'forecast/partials/dashboard_content.html', context)

    return render(request, 'forecast/forecast_dashboard.html', context)


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
    Unified View with Dynamic KPIs based on filtered results.
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
    selected_month = request.GET.get('month', '').strip()
    if selected_month:
        filtered_by_month = []
        for group in grouped_list:
            if group['period'].strftime('%Y-%m') == selected_month:
                filtered_by_month.append(group)
        grouped_list = filtered_by_month

    # 5. Filter by Search
    query = request.GET.get('q', '').strip().lower()
    if query:
        filtered_list = []
        for group in grouped_list:
            match_product = (query in group['product'].sku.lower()) or (query in group['product'].description.lower())
            match_country = any(query in d['country'].lower() for d in group['details'])
            if match_product or match_country:
                filtered_list.append(group)
        grouped_list = filtered_list

    # === [NEW] Calculate KPIs based on Filtered Data ===
    kpi_total_orders = 0
    kpi_allocated_pending = 0
    kpi_shipped = 0

    for group in grouped_list:
        kpi_total_orders += group['total_actual']
        kpi_allocated_pending += group['total_allocated'] # This is reserved/pending

        # To get shipped qty, we must look at details because it's not in the group sum
        for detail in group['details']:
            if detail['actual_obj'] and detail['actual_obj'].shipped_date:
                kpi_shipped += detail['actual_qty']

    if kpi_total_orders > 0:
        kpi_fulfillment_rate = (kpi_shipped / kpi_total_orders) * 100
    else:
        kpi_fulfillment_rate = 0

    sort_by = request.GET.get('sort', 'date_asc')
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

    if grouped_list:
        product_ids = set(g['product'].id for g in grouped_list)
        snapshots = InventorySnapshot.objects.filter(product_id__in=product_ids).order_by('product_id', '-snapshot_date')
        stock_map = {}
        for s in snapshots:
            if s.product_id not in stock_map:
                stock_map[s.product_id] = s.quantity_on_hand - s.quantity_reserved
        for group in grouped_list:
            pid = group['product'].id
            group['available_stock'] = stock_map.get(pid, 0)

    # [KEY FIX] Pass Active Shipments to Context
    active_shipments = OutboundShipment.objects.filter(status='PLANNING').order_by('etd')

    context = {
        'grouped_demands': grouped_list,
        'import_form': ImportDemandForm(),
        'current_sort': sort_by,
        'current_query': request.GET.get('q', ''),
        'current_month_filter': selected_month,
        'active_shipments': active_shipments,

        # KPIs
        'kpi_total_orders': kpi_total_orders,
        'kpi_allocated_pending': kpi_allocated_pending,
        'kpi_shipped': kpi_shipped,
        'kpi_fulfillment_rate': kpi_fulfillment_rate,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'forecast/partials/sales_forecast_content.html', context)

    return render(request, 'forecast/sales_forecast.html', context)


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
        # 获取用户勾选的 entry IDs
        selected_ids = request.POST.getlist('selected_entries')

        if selected_ids:
            count = convert_entries_to_orders(selected_ids)
            if count > 0:
                messages.success(request, f"成功创建 {count} 张生产工单 (Draft)。")
                # 检查是否全部转换完成，如果是，锁定计划
                if not plan.entries.filter(production_order__isnull=True).exists():
                    plan.is_locked = True
                    plan.save()
            else:
                messages.warning(request, "未生成任何工单（可能已转换过）。")
        else:
            messages.warning(request, "请先勾选需要转换的生产建议。")

        return redirect('forecast:plan_detail', pk=pk)

    return render(request, 'forecast/plan_detail.html', {'plan': plan})


def delete_plan(request, pk):
    plan = get_object_or_404(ForecastPlan, pk=pk)
    plan.delete()
    messages.success(request, "Plan deleted.")
    return redirect('forecast:dashboard')
