from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from django.db.models import F
import random

from inventory.models import InventorySnapshot, BillOfMaterial, Product
from .models import ProductionOrder, ProductionComponent

def generate_order_number():
    """生成唯一工单号 PO-YYYYMMDD-XXXX"""
    today = timezone.now().strftime('%Y%m%d')
    rand = random.randint(1000, 9999)
    return f"PO-{today}-{rand}"

def release_reserved_stock(order):
    """
    [清理函数] 用于完全重算 BOM 时。
    1. 如果工单之前是 硬锁定状态 (Confirmed/In Progress)，释放 InventorySnapshot 中的库存。
    2. 删除所有的 ProductionComponent 记录 (准备重新生成)。
    """
    # 只有处于硬锁定状态的订单，才真正占用了 InventorySnapshot 的 Reserved 字段
    is_hard_locked = order.status in ['CONFIRMED', 'IN_PROGRESS']

    existing_components = order.components.all()
    if existing_components.exists():
        if is_hard_locked:
            for comp in existing_components:
                InventorySnapshot.objects.filter(product=comp.component).update(
                    quantity_reserved=F('quantity_reserved') - comp.quantity_required
                )

        # 无论是否锁定，都要删除旧的组件记录 (因为要重算)
        existing_components.delete()

def calculate_requirements(order):
    """
    [核心计算] 计算原料需求。
    1. 清理旧数据。
    2. 生成新组件记录 (ProductionComponent)。
    3. 仅当工单是 'CONFIRMED' 或 'IN_PROGRESS' 时，才更新 InventorySnapshot 的 Reserved。
    """
    # 1. 清理旧状态
    release_reserved_stock(order)

    # 2. 计算新需求
    bom_lines = BillOfMaterial.objects.filter(product=order.product)

    for line in bom_lines:
        qty_per_unit = Decimal(str(line.quantity))
        order_qty = Decimal(str(order.quantity))
        required_qty = qty_per_unit * order_qty

        # 创建组件记录 (Soft Allocation)
        # 无论 Draft 还是 Confirmed，这个记录都必须有，用于 Inventory 界面的 "Budgeted" 显示
        ProductionComponent.objects.create(
            production_order=order,
            component=line.component,
            quantity_required=required_qty,
            quantity_used=required_qty
        )

        # 3. 如果是硬锁定状态，则更新 InventorySnapshot (Hard Reservation)
        if order.status in ['CONFIRMED', 'IN_PROGRESS']:
            snapshot = InventorySnapshot.objects.filter(
                product=line.component
            ).order_by('-snapshot_date').first()

            if snapshot:
                snapshot.quantity_reserved = F('quantity_reserved') + required_qty
                snapshot.save()
            else:
                # 极端情况：如果没有库存快照，创建一个
                InventorySnapshot.objects.create(
                    product=line.component,
                    snapshot_date=timezone.now().date(),
                    quantity_on_hand=0,
                    quantity_reserved=required_qty
                )

def lock_stock_for_order(order):
    """
    [状态流转] Draft -> Confirmed
    工单确认时调用。遍历已有的组件记录，将需求累加到 InventorySnapshot。
    """
    if order.status not in ['CONFIRMED', 'IN_PROGRESS']:
        return

    for comp in order.components.all():
        snapshot = InventorySnapshot.objects.filter(
            product=comp.component
        ).order_by('-snapshot_date').first()

        if snapshot:
            snapshot.quantity_reserved = F('quantity_reserved') + comp.quantity_required
            snapshot.save()
        else:
            InventorySnapshot.objects.create(
                product=comp.component,
                snapshot_date=timezone.now().date(),
                quantity_on_hand=0,
                quantity_reserved=comp.quantity_required
            )

def unlock_stock_for_order(order):
    """
    [状态流转] Confirmed -> Cancelled / Draft
    取消或回退工单时调用。释放 InventorySnapshot 的 Reserved。
    【修复】改为明确获取最新快照并扣减，确保与 lock 逻辑对称。
    """
    for comp in order.components.all():
        # 1. 查找该原料的最新库存快照 (与 lock_stock_for_order 逻辑一致)
        snapshot = InventorySnapshot.objects.filter(
            product=comp.component
        ).order_by('-snapshot_date').first()

        if snapshot:
            # 2. 执行扣减 (使用 F 表达式防止并发问题)
            # 逻辑：Reserved = Reserved - Requirement
            snapshot.quantity_reserved = F('quantity_reserved') - comp.quantity_required
            snapshot.save()

            # 注意：理论上 quantity_reserved 不应小于 0，但 F() 表达式在 DB 层执行，
            # 如果之前的逻辑正确，这里减去自己加上的数，必然归零或减少回原值。

@transaction.atomic
def complete_production(order):
    """
    [完成生产] Confirmed -> Completed
    1. 扣减原料 OH (同时减少 Reserved)。
    2. 增加成品 OH。
    """
    if order.status == 'COMPLETED':
        return

    today = timezone.now().date()

    # --- A. 原料处理 ---
    for line in order.components.all():
        comp = line.component
        qty_used = line.quantity_used

        # 1. 释放预留 (Reserved - Qty)
        # 因为生产完成了，预留任务结束。同时我们要扣减实物。
        # 逻辑：InventorySnapshot.reserved -= qty_required
        # 逻辑：InventorySnapshot.on_hand -= qty_used

        # 获取快照
        snapshot = InventorySnapshot.objects.filter(product=comp).order_by('-snapshot_date').first()
        if not snapshot:
            snapshot = InventorySnapshot.objects.create(product=comp, snapshot_date=today, quantity_on_hand=0)

        # 执行扣减
        # 注意：这里假设 quantity_used ~= quantity_required，或者无论用了多少，预留都应该清零
        snapshot.quantity_on_hand -= qty_used
        snapshot.quantity_reserved -= line.quantity_required # 释放之前的锁定
        snapshot.save()

    # --- B. 成品处理 ---
    fg = order.product
    fg_qty = order.quantity

    fg_snapshot = InventorySnapshot.objects.filter(product=fg).order_by('-snapshot_date').first()
    if not fg_snapshot:
        fg_snapshot = InventorySnapshot.objects.create(product=fg, snapshot_date=today, quantity_on_hand=0)

    fg_snapshot.quantity_on_hand += fg_qty
    fg_snapshot.save()

    # --- C. 状态更新 ---
    order.status = 'COMPLETED'
    order.save()
