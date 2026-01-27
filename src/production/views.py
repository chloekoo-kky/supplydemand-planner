import json


from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import F, Sum, Subquery, OuterRef, Min, Max
from decimal import Decimal
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from inventory.models import Product, InventorySnapshot, BillOfMaterial
from .models import ProductionOrder, ProductionComponent
from .services import (
    generate_order_number, calculate_requirements,
    complete_production, lock_stock_for_order,
    unlock_stock_for_order
)



def production_dashboard(request):
    """
    Production Overview with Time-Phased Inventory Logic (APS Level 1).
    Orders are calculated sequentially based on start_date to determine true availability.
    """
    # 1. 获取所有关联数据
    # 按 start_date 排序是关键，确保先生产的先分配库存
    orders = ProductionOrder.objects.select_related('product') \
                                    .prefetch_related('components__component') \
                                    .all().order_by('start_date', 'created_at')

    fgs = Product.objects.filter(nature='FG').order_by('sku')

    # 2. 构建初始库存池 (Running Balance)
    # 获取所有相关原料的当前 SOH (Quantity On Hand)
    # 注意：我们这里用 SOH (实物库存) 作为起点进行推演，而不只是 Net Available
    # 因为我们要重新模拟所有 Confirmed/Draft 订单的占用过程
    comp_product_ids = set()
    for o in orders:
        if o.status in ['DRAFT', 'CONFIRMED', 'IN_PROGRESS']:
            for c in o.components.all():
                comp_product_ids.add(c.component_id)

    inventory_pool = {} # { product_id: float(current_soh) }

    if comp_product_ids:
        # 获取最新快照
        sq = InventorySnapshot.objects.filter(product=OuterRef('product')).order_by('-snapshot_date')
        snapshots = InventorySnapshot.objects.filter(
            pk=Subquery(sq.values('pk')[:1]),
            product_id__in=comp_product_ids
        )
        for snap in snapshots:
            inventory_pool[snap.product_id] = float(snap.quantity_on_hand)

    # 3. 核心算法：Time-Phased Allocation (基于时间的分配)
    for order in orders:
        # 只计算未完成的订单
        if order.status in ['DRAFT', 'CONFIRMED', 'IN_PROGRESS']:

            # 标记该订单整体是否齐套
            order_is_fully_stocked = True

            for comp in order.components.all():
                pid = comp.component_id
                required = float(comp.quantity_required)

                # 获取当前池子里的剩余量
                current_balance = inventory_pool.get(pid, 0.0)

                # 记录给前端显示的“当时可用量”
                # 这里的 display_stock 代表：轮到这个订单生产时，仓库里还剩多少
                comp.display_stock = current_balance

                # 判断是否足够
                if current_balance >= required:
                    comp.is_enough = True
                    comp.shortage = 0
                    # 扣减库存 (预演)
                    inventory_pool[pid] = current_balance - required
                else:
                    comp.is_enough = False
                    comp.shortage = required - current_balance
                    order_is_fully_stocked = False
                    # 库存耗尽，设为0 (不能扣成负数，否则后续订单显示的 Available 会很奇怪)
                    inventory_pool[pid] = 0

        else:
            # 已完成/取消的订单，不参与计算，或者仅做简单展示
            for comp in order.components.all():
                comp.is_enough = True
                comp.display_stock = 0 # 不重要

    # 4. 如果用户想按倒序查看列表 (UI习惯)，我们可以在计算完后再反转列表
    # 但保留计算结果（display_stock 已经是计算好的值了）
    orders_list = list(orders)
    # 比如我们想把最近日期的放前面显示，或者按用户原本的习惯
    # orders_list.sort(key=lambda x: x.start_date, reverse=True)

    context = {
        'orders': orders_list,
        'fgs': fgs,
        'page_title': 'Production Orders'
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'production/partials/dashboard_content.html', context)

    return render(request, 'production/production_dashboard.html', context)


def production_update_status(request, pk):
    """
    Update Production Order Status (via Edit Modal)
    Handles side effects like Locking/Unlocking stock AND Completing Production.
    """
    order = get_object_or_404(ProductionOrder, pk=pk)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        old_status = order.status

        # Prevent editing Completed orders
        if old_status == 'COMPLETED':
            messages.error(request, "Cannot change status of a Completed order.")
            return redirect('production:dashboard')

        if old_status == 'IN_PROGRESS' and new_status in ['DRAFT', 'CONFIRMED']:
            messages.error(request, "⚠️ Production Started: Cannot revert to Draft or Confirmed.")
            return redirect('production:dashboard')

        if new_status and new_status != old_status:
            try:
                # === FIX: Handle Completion Logic Here ===
                if new_status == 'COMPLETED':
                    if old_status in ['CONFIRMED', 'IN_PROGRESS']:
                        # Call the service that handles stock deduction and FG entry
                        complete_production(order)
                        messages.success(request, f"Order {order.order_number} completed. Stock updated.")
                        return redirect('production:dashboard')
                    else:
                        messages.error(request, "Order must be Confirmed or In Progress to complete.")
                        return redirect('production:dashboard')

                # === Normal Status Updates (Non-Completion) ===

                # Update status in memory first
                order.status = new_status

                # 1. Logic: Moving TO Confirmed/In_Progress (Lock Stock)
                if new_status in ['CONFIRMED', 'IN_PROGRESS'] and old_status not in ['CONFIRMED', 'IN_PROGRESS']:
                    lock_stock_for_order(order)
                    msg_extra = "Stock Reserved."

                # 2. Logic: Moving FROM Confirmed/In_Progress TO Draft/Cancelled (Unlock Stock)
                elif new_status in ['DRAFT', 'CANCELLED'] and old_status in ['CONFIRMED', 'IN_PROGRESS']:
                    unlock_stock_for_order(order)
                    msg_extra = "Reservations Released."
                else:
                    msg_extra = "Status Updated."

                order.save()
                messages.success(request, f"Order {order.order_number} updated to {new_status}. {msg_extra}")

            except Exception as e:
                messages.error(request, f"Error updating status: {str(e)}")

    return redirect('production:dashboard')


def production_create(request):
    """Create Order (Draft or Confirmed)"""
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        qty = request.POST.get('quantity')
        date = request.POST.get('start_date')
        status = request.POST.get('status', 'DRAFT')

        if product_id and qty:
            order = ProductionOrder.objects.create(
                order_number=generate_order_number(),
                product_id=product_id,
                quantity=qty,
                start_date=date,
                status=status
            )

            calculate_requirements(order)

            msg = f"Order {order.order_number} created."
            if status == 'DRAFT':
                msg += " (Draft Mode: Soft Allocated)"
            elif status == 'CONFIRMED':
                msg += " (Confirmed: Stock Reserved)"

            messages.success(request, msg)

            return redirect('production:dashboard') # Redirect to dashboard now

    return redirect('production:dashboard')


def production_update_quantity(request, pk):
    """Update Order Quantity (Draft Only)"""
    order = get_object_or_404(ProductionOrder, pk=pk)

    if order.status != 'DRAFT':
        messages.error(request, "Only DRAFT orders can be edited. Please revert to Draft first.")
        return redirect('production:detail', pk=pk)

    if request.method == 'POST':
        new_qty = request.POST.get('quantity')

        try:
            new_qty_float = float(new_qty)
            if new_qty and new_qty_float > 0:
                order.quantity = new_qty
                order.save()
                calculate_requirements(order)
                messages.success(request, f"Draft updated to {new_qty}. BOM Requirements recalculated.")
            else:
                messages.error(request, "Invalid quantity.")
        except ValueError:
            messages.error(request, "Invalid quantity format.")

    return redirect('production:dashboard')


def production_detail(request, pk):
    """
    Detailed view with full logic (kept for fallback or detailed analysis)
    """
    order = get_object_or_404(ProductionOrder, pk=pk)

    components_data = []
    for comp_line in order.components.select_related('component').all():
        latest_stock = InventorySnapshot.objects.filter(
            product=comp_line.component
        ).order_by('-snapshot_date').first()

        on_hand = float(latest_stock.quantity_on_hand) if latest_stock else 0.0
        reserved = float(latest_stock.quantity_reserved) if latest_stock else 0.0

        # Net Available = SOH - Reserved
        net_available = on_hand - reserved

        # Effective Available Logic (SOH - Reserved_by_Others)
        total_reserved = reserved
        my_reserved_qty = 0.0
        if order.status in ['CONFIRMED', 'IN_PROGRESS']:
            my_reserved_qty = float(comp_line.quantity_required)

        reserved_by_others = max(0.0, total_reserved - my_reserved_qty)
        effective_available = on_hand - reserved_by_others

        # Determine check logic
        if order.status == 'DRAFT':
            stock_for_check = net_available
            display_stock = net_available
            stock_label = "Net Avail"
        else:
            stock_for_check = effective_available
            display_stock = effective_available
            stock_label = "Effective Avail"

        components_data.append({
            'line': comp_line,
            'sku': comp_line.component.sku,
            'name': comp_line.component.description,
            'required_qty': comp_line.quantity_required,
            'current_stock': on_hand,
            'net_available': net_available,
            'reserved': reserved,
            'display_stock': display_stock,
            'stock_label': stock_label,
            'my_reserved': my_reserved_qty,
            'is_enough': stock_for_check >= float(comp_line.quantity_required),
            'shortage': max(0, float(comp_line.quantity_required) - stock_for_check)
        })

    context = {
        'order': order,
        'components': components_data,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'production/partials/production_detail_modal.html', context)

    return render(request, 'production/production_detail.html', context)


def production_action(request, pk, action):
    """Handle Status Changes: Confirm, Complete, Cancel"""
    order = get_object_or_404(ProductionOrder, pk=pk)

    if request.method == 'POST':
        if action == 'confirm':
            if order.status == 'DRAFT':
                order.status = 'CONFIRMED'
                order.save()
                lock_stock_for_order(order)
                messages.success(request, f"Order {order.order_number} confirmed. Stock reserved.")
            else:
                messages.warning(request, "Only DRAFT orders can be confirmed.")

        elif action == 'complete':
            try:
                complete_production(order)
                messages.success(request, f"Production {order.order_number} completed! Stock updated.")
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")

        elif action == 'cancel':
            was_locked = order.status in ['CONFIRMED', 'IN_PROGRESS']
            if order.status != 'COMPLETED':
                if was_locked:
                    unlock_stock_for_order(order)
                order.status = 'CANCELLED'
                order.save()
                messages.warning(request, "Order cancelled. Reservations released.")
            else:
                messages.error(request, "Cannot cancel a completed order.")

    return redirect('production:dashboard')


def get_product_max_capacity(request):
    """API: Simple Max Capacity based on BOM and SOH"""
    product_id = request.GET.get('product_id')
    if not product_id:
        return JsonResponse({'max_qty': 0})

    bom_lines = BillOfMaterial.objects.filter(product_id=product_id)
    if not bom_lines.exists():
        return JsonResponse({'max_qty': 0, 'reason': 'No BOM found'})

    max_possible_list = []
    for line in bom_lines:
        component = line.component
        qty_required = line.quantity

        latest_stock = InventorySnapshot.objects.filter(
            product=component
        ).order_by('-snapshot_date').first()
        current_stock = latest_stock.quantity_on_hand if latest_stock else 0

        if qty_required > 0:
            possible_yield = int(current_stock // qty_required)
            max_possible_list.append(possible_yield)

    final_max_qty = min(max_possible_list) if max_possible_list else 0
    return JsonResponse({'max_qty': final_max_qty})


def calculate_production_capacity(request):
    """
    API: Estimator Logic
    Returns max producible quantity based on PROJECTED availability.
    """
    product_id = request.GET.get('product_id')

    # === FIX: Handle empty string for quantity safely ===
    try:
        raw_qty = request.GET.get('quantity', 0)
        quantity = float(raw_qty) if raw_qty else 0.0
    except ValueError:
        quantity = 0.0

    if not product_id:
        return JsonResponse({'error': 'Product required'}, status=400)

    bom_lines = BillOfMaterial.objects.filter(product_id=product_id).select_related('component')

    if not bom_lines.exists():
        return JsonResponse({'error': 'No BOM found'}, status=400)

    components_data = []
    max_producible = float('inf')

    for line in bom_lines:
        required_qty = float(line.quantity) * quantity

        latest_stock = InventorySnapshot.objects.filter(
            product=line.component
        ).order_by('-snapshot_date').first()

        on_hand = float(latest_stock.quantity_on_hand) if latest_stock else 0.0
        reserved = float(latest_stock.quantity_reserved) if latest_stock else 0.0

        net_available = on_hand - reserved

        budgeted_agg = ProductionComponent.objects.filter(
            component=line.component,
            production_order__status='DRAFT'
        ).aggregate(total=Sum('quantity_required'))

        budgeted = float(budgeted_agg['total'] or 0.0)
        projected_available = net_available - budgeted
        stock_for_calc = max(0, projected_available)

        if line.quantity > 0:
            limit_by_component = int(stock_for_calc // float(line.quantity))
            if limit_by_component < max_producible:
                max_producible = limit_by_component

        components_data.append({
            'sku': line.component.sku,
            'required': required_qty,
            'projected_available': projected_available,
            'status': 'OK' if stock_for_calc >= required_qty else 'SHORTAGE',
        })

    if max_producible == float('inf'):
        max_producible = 0

    return JsonResponse({
        'components': components_data,
        'max_possible': max_producible,
        'is_feasible': max_producible >= quantity
    })



def production_calendar(request):
    """渲染日历主页面"""
    context = {
        'page_title': 'Production Schedule'
    }

    # === 关键修改：如果是 AJAX 请求，只返回局部内容 ===
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'production/partials/calendar_content.html', context)

    # 如果是直接刷新页面，返回包含 Sidebar 的完整页面
    return render(request, 'production/calendar.html', context)

def calendar_events_api(request):
    """
    API: 为 FullCalendar 提供 JSON 数据
    """
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')

    # === 关键修复 1: 日期格式化 ===
    # FullCalendar 发送的是 ISO 格式 (e.g., 2026-01-26T00:00:00Z)
    # 我们只取前 10 位 (YYYY-MM-DD) 以匹配数据库的 DateField
    start_date = start_str[:10] if start_str else None
    end_date = end_str[:10] if end_str else None

    # 构建查询
    query = ProductionOrder.objects.select_related('product').all()
    if start_date:
        query = query.filter(start_date__gte=start_date)
    if end_date:
        query = query.filter(start_date__lte=end_date)

    orders = query

    events = []
    for order in orders:
        # Visual Management: 颜色编码
        color = '#9ca3af'     # Gray (Draft)
        border_color = '#9ca3af'

        editable = True

        # === 关键修复 2: 修正拼写 CANCELED (1个L) 以匹配 models.py ===
        if order.status == 'CONFIRMED':
            color = '#2563eb' # Blue
            border_color = '#1d4ed8'
        elif order.status == 'IN_PROGRESS':
            color = "#e5a546" # Orange
            border_color = "#c56a15"
            editable = False
        elif order.status == 'COMPLETED':
            color = '#059669' # Emerald
            border_color = '#065f46'
            editable = False
        elif order.status == 'CANCELED': # 注意这里是 1 个 L
            color = '#ef4444' # Red
            editable = False

        events.append({
            'id': order.id,
            'title': f"{order.product.sku} ({int(order.quantity)})",
            'start': order.start_date.isoformat(),
            'backgroundColor': color,
            'borderColor': border_color,
            'textColor': '#ffffff',
            'allDay': True,
            'editable': editable,
            'extendedProps': {
                'status': order.get_status_display(),
                'status_raw': order.status,
                'po_number': order.order_number,
            }
        })

    return JsonResponse(events, safe=False)

@csrf_exempt # 简化演示，实际项目建议保留 CSRF 保护
@require_POST
def calendar_move_api(request):
    """
    API: 处理拖拽后的日期更新
    """
    try:
        data = json.loads(request.body)
        event_id = data.get('id')
        new_date_str = data.get('new_date') # 格式 YYYY-MM-DD

        order = ProductionOrder.objects.get(id=event_id)

        # 业务规则检查：
        # 1. 如果订单已经 COMPLETED 或 IN_PROGRESS，前端虽然禁用了，后端也要防守
        if order.status not in ['DRAFT', 'CONFIRMED']:
            return JsonResponse({'status': 'error', 'message': 'Locked orders cannot be moved.'}, status=403)

        # 2. 更新日期
        order.start_date = new_date_str
        order.save()

        return JsonResponse({'status': 'ok', 'message': f'Order {order.order_number} moved to {new_date_str}'})

    except ProductionOrder.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Order not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def production_complete_submission(request, pk):
    """
    Handle the 'Complete Production' modal submission.
    Updates Actual FG Qty and Actual Component Usage before finalizing.
    """
    order = get_object_or_404(ProductionOrder, pk=pk)

    if request.method == 'POST':
        try:
            # 1. Update FG Actual Quantity (Updates the Order Record)
            actual_fg_qty = request.POST.get('actual_fg_qty')
            if actual_fg_qty:
                order.quantity = float(actual_fg_qty)
                order.save()

            # 2. Update Component Actual Usage
            # Iterate through POST data to find component inputs
            for key, value in request.POST.items():
                if key.startswith('comp_usage_'):
                    comp_id = key.replace('comp_usage_', '')
                    try:
                        usage_qty = float(value)
                        # Fetch the specific component record
                        comp = order.components.get(id=comp_id)
                        comp.quantity_used = usage_qty
                        comp.save()
                    except (ValueError, ProductionComponent.DoesNotExist):
                        continue # Skip invalid data

            # 3. Finalize Production (Stock Transactions)
            complete_production(order)
            messages.success(request, f"Production completed! FG: {order.quantity}, Materials deducted.")

        except Exception as e:
            messages.error(request, f"Error completing production: {str(e)}")

    return redirect('production:detail', pk=pk)
