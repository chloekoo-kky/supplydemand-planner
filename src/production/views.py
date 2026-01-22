from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import F, Sum, Subquery, OuterRef, Min
from decimal import Decimal

from inventory.models import Product, InventorySnapshot, BillOfMaterial
from .models import ProductionOrder
from .services import (
    generate_order_number, calculate_requirements,
    complete_production, lock_stock_for_order,
    unlock_stock_for_order
)


def production_dashboard(request):
    """生产概览列表"""
    orders = ProductionOrder.objects.select_related('product').all().order_by('-start_date')

    fgs = Product.objects.filter(nature='FG').order_by('sku')

    context = {
        'orders': orders,
        'fgs': fgs,  # 【关键】把 fgs 传给模板，否则下拉菜单就是空的
        'page_title': 'Production Orders'
    }

    # 【新增】核心逻辑：如果是 AJAX 请求，只返回局部内容
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'production/partials/dashboard_content.html', context)

    # 否则返回包含 Base 的完整页面
    return render(request, 'production/production_dashboard.html', context)

def production_create(request):
    """创建工单 (Draft 或 Confirmed)"""
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        qty = request.POST.get('quantity')
        date = request.POST.get('start_date')

        # 【修改点】默认状态改为 DRAFT (预算模式)
        # 前端如果选择了 "Confirm / Queue"，这里会接收到 'CONFIRMED'
        status = request.POST.get('status', 'DRAFT')

        if product_id and qty:
            order = ProductionOrder.objects.create(
                order_number=generate_order_number(),
                product_id=product_id,
                quantity=qty,
                start_date=date,
                status=status
            )

            # 【核心保留】计算原料需求 (生成 ProductionComponent)
            # 这一步至关重要，因为它生成的数据会被 Inventory 视图读取：
            # - 如果是 DRAFT，Inventory 显示为 "Budgeted" (软预留)
            # - 如果是 CONFIRMED，Inventory 显示为 "Locked" (硬预留)
            calculate_requirements(order)

            msg = f"Order {order.order_number} created."
            if status == 'DRAFT':
                msg += " (Draft Mode: Soft Allocated)"
            elif status == 'CONFIRMED':
                msg += " (Confirmed: Stock Reserved)"

            messages.success(request, msg)

            return redirect('production:detail', pk=order.id)

    # 如果是 GET 请求，通常重定向回列表或显示空表单（视你原来的逻辑而定）
    return redirect('production:dashboard')


def production_update_quantity(request, pk):
    """更新工单数量 (仅限 Draft)"""
    order = get_object_or_404(ProductionOrder, pk=pk)

    # 【修改点】只允许修改 DRAFT 状态
    # 如果工单已经 CONFIRMED (锁定库存) 或 IN_PROGRESS，修改数量需要更谨慎的操作（如先 Cancel 或 Revert）
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

                # 【核心保留】重新计算需求
                # 这会自动更新 ProductionComponent 表，从而刷新 Inventory 里的 "Budgeted" 数量
                calculate_requirements(order)

                messages.success(request, f"Draft updated to {new_qty}. BOM Requirements recalculated.")
            else:
                messages.error(request, "Invalid quantity.")
        except ValueError:
            messages.error(request, "Invalid quantity format.")

    return redirect('production:detail', pk=pk)


def production_detail(request, pk):
    """工单详情：显示BOM需求和库存检查"""
    order = get_object_or_404(ProductionOrder, pk=pk)

    # 获取原料需求，并附带当前库存进行对比
    components_data = []
    for comp_line in order.components.select_related('component').all():
        latest_stock = InventorySnapshot.objects.filter(
            product=comp_line.component
        ).order_by('-snapshot_date').first()

        current_stock = latest_stock.quantity_on_hand if latest_stock else 0

        # 为了配合 modal 模板，这里需要加上 sku, name 等字段
        components_data.append({
            'line': comp_line,
            'sku': comp_line.component.sku,           # 新增
            'name': comp_line.component.description,  # 新增
            'required_qty': comp_line.quantity_required, # 新增
            'current_stock': current_stock,
            'is_enough': current_stock >= comp_line.quantity_required,
            'shortage': max(0, comp_line.quantity_required - current_stock) # 新增
        })

    context = {
        'order': order,
        'components': components_data,
    }

    # 【新增】如果是 AJAX 请求 (来自 Dashboard 弹窗)，只返回 Modal 内容
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'production/partials/production_detail_modal.html', context)

    # 否则返回完整页面 (直接访问链接时)
    return render(request, 'production/production_detail.html', context)


def production_action(request, pk, action):
    """处理状态变更：Confirm, Complete, Cancel"""
    order = get_object_or_404(ProductionOrder, pk=pk)

    if request.method == 'POST':
        # 1. Confirm: Draft -> Confirmed (锁定库存)
        if action == 'confirm':
            if order.status == 'DRAFT':
                order.status = 'CONFIRMED'
                order.save()

                # 【关键】调用服务锁定库存
                lock_stock_for_order(order)

                messages.success(request, f"Order {order.order_number} confirmed. Stock reserved.")
            else:
                messages.warning(request, "Only DRAFT orders can be confirmed.")

        # 2. Complete: Confirmed -> Completed (扣减库存，成品入库)
        elif action == 'complete':
            try:
                complete_production(order)
                messages.success(request, f"Production {order.order_number} completed! Stock updated.")
            except Exception as e:
                messages.error(request, f"Error: {str(e)}")

        # 3. Cancel: Any -> Cancelled (释放库存)
        elif action == 'cancel':
            # 记录旧状态，判断是否需要释放库存
            was_locked = order.status in ['CONFIRMED', 'IN_PROGRESS']

            if order.status != 'COMPLETED':
                # 如果之前是锁定状态，先释放库存
                if was_locked:
                    unlock_stock_for_order(order)

                order.status = 'CANCELLED'
                order.save()
                messages.warning(request, "Order cancelled. Reservations released.")
            else:
                messages.error(request, "Cannot cancel a completed order.")

    return redirect('production:detail', pk=pk)



def get_product_max_capacity(request):
    """
    API: 根据 BOM 和当前库存计算某成品的最大可生产数量
    """
    product_id = request.GET.get('product_id')
    if not product_id:
        return JsonResponse({'max_qty': 0})

    # 1. 获取该产品的 BOM 结构
    bom_lines = BillOfMaterial.objects.filter(product_id=product_id)

    if not bom_lines.exists():
        # 如果没有 BOM (配方)，默认无法计算或设为 0 (或者无限，视业务而定，这里设为0较安全)
        return JsonResponse({'max_qty': 0, 'reason': 'No BOM found'})

    max_possible_list = []

    # 2. 遍历每一个原料，计算它能支持生产多少成品
    for line in bom_lines:
        component = line.component
        qty_required = line.quantity  # 生产 1 个成品需要的原料数量

        # 获取该原料的最新库存
        latest_stock = InventorySnapshot.objects.filter(
            product=component
        ).order_by('-snapshot_date').first()

        current_stock = latest_stock.quantity_on_hand if latest_stock else 0

        if qty_required > 0:
            # 向下取整：库存 / 单耗
            possible_yield = int(current_stock // qty_required)
            max_possible_list.append(possible_yield)
        else:
            # 如果单耗为0 (异常数据)，则不限制
            pass

    # 3. 取所有原料计算结果的最小值 (木桶效应)
    # 如果列表为空 (BOM里没原料)，则为 0
    final_max_qty = min(max_possible_list) if max_possible_list else 0

    return JsonResponse({'max_qty': final_max_qty})



def calculate_production_capacity(request):
    """
    API: 生产试算
    输入: product_id, quantity
    输出: BOM原料详情列表，标记谁是瓶颈
    """
    product_id = request.GET.get('product_id')
    quantity = float(request.GET.get('quantity', 0))

    if not product_id:
        return JsonResponse({'error': 'Product required'}, status=400)

    bom_lines = BillOfMaterial.objects.filter(product_id=product_id).select_related('component')

    if not bom_lines.exists():
        return JsonResponse({'error': 'No BOM found for this product'}, status=400)

    components_data = []
    max_producible = float('inf') # 无限大初始值

    for line in bom_lines:
        required_qty = float(line.quantity) * quantity

        # 获取当前库存
        latest_stock = InventorySnapshot.objects.filter(
            product=line.component
        ).order_by('-snapshot_date').first()

        current_stock = float(latest_stock.quantity_on_hand) if latest_stock else 0.0

        # 计算该原料最多能支持做多少成品
        if line.quantity > 0:
            limit_by_component = int(current_stock // float(line.quantity))
            if limit_by_component < max_producible:
                max_producible = limit_by_component

        components_data.append({
            'sku': line.component.sku,
            'name': line.component.description,
            'required': required_qty,
            'stock': current_stock,
            'status': 'OK' if current_stock >= required_qty else 'SHORTAGE',
            'shortage_qty': max(0, required_qty - current_stock)
        })

    # 如果没有限制因素（比如不需要原料），虽然不太可能
    if max_producible == float('inf'):
        max_producible = 0

    return JsonResponse({
        'components': components_data,
        'max_possible': max_producible,
        'is_feasible': max_producible >= quantity
    })
