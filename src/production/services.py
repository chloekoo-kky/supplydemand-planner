import logging
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from django.db.models import F
import random

from inventory.models import InventorySnapshot, BillOfMaterial, Product
from .models import ProductionOrder, ProductionComponent

# Setup Logger
logger = logging.getLogger(__name__)

def generate_order_number():
    """生成唯一工单号 PO-YYYYMMDD-XXXX"""
    today = timezone.now().strftime('%Y%m%d')
    rand = random.randint(1000, 9999)
    return f"PO-{today}-{rand}"

def release_reserved_stock(order):
    """
    [清理函数] 用于完全重算 BOM 时。
    """
    is_hard_locked = order.status in ['CONFIRMED', 'IN_PROGRESS']

    existing_components = order.components.all()
    if existing_components.exists():
        if is_hard_locked:
            for comp in existing_components:
                InventorySnapshot.objects.filter(product=comp.component).update(
                    quantity_reserved=F('quantity_reserved') - comp.quantity_required
                )

        existing_components.delete()

def calculate_requirements(order):
    """
    [核心计算] 计算原料需求。
    """
    release_reserved_stock(order)

    bom_lines = BillOfMaterial.objects.filter(product=order.product)

    for line in bom_lines:
        qty_per_unit = Decimal(str(line.quantity))
        order_qty = Decimal(str(order.quantity))
        required_qty = qty_per_unit * order_qty

        ProductionComponent.objects.create(
            production_order=order,
            component=line.component,
            quantity_required=required_qty,
            quantity_used=required_qty
        )

        if order.status in ['CONFIRMED', 'IN_PROGRESS']:
            snapshot = InventorySnapshot.objects.filter(
                product=line.component
            ).order_by('-snapshot_date').first()

            if snapshot:
                snapshot.quantity_reserved = F('quantity_reserved') + required_qty
                snapshot.save()
            else:
                InventorySnapshot.objects.create(
                    product=line.component,
                    snapshot_date=timezone.now().date(),
                    quantity_on_hand=0,
                    quantity_reserved=required_qty
                )

def lock_stock_for_order(order):
    """
    [状态流转] Draft -> Confirmed
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
    """
    for comp in order.components.all():
        snapshot = InventorySnapshot.objects.filter(
            product=comp.component
        ).order_by('-snapshot_date').first()

        if snapshot:
            snapshot.quantity_reserved = F('quantity_reserved') - comp.quantity_required
            snapshot.save()

@transaction.atomic
def complete_production(order):
    """
    [完成生产] Confirmed -> Completed
    Includes Debug Logging and Snapshot Carry Forward Logic.
    """
    logger.info(f"=== START COMPLETE PRODUCTION: {order.order_number} ===")

    if order.status not in ['CONFIRMED', 'IN_PROGRESS']:
        logger.warning(f"Order status invalid for completion: {order.status}")
        if order.status == 'COMPLETED':
            return
        raise ValueError(f"Order must be CONFIRMED or IN_PROGRESS. Current: {order.status}")

    today = timezone.now().date()
    logger.info(f"Transaction Date: {today}")

    # --- A. 原料处理 (Raw Materials) ---
    logger.info(f"--- Processing Components ({order.components.count()} items) ---")

    for line in order.components.all():
        comp = line.component
        logger.info(f"> Processing Component: {comp.sku}")

        # 1. 确定扣减数量
        qty_to_deduct = line.quantity_used
        if qty_to_deduct is None or qty_to_deduct <= 0:
            logger.info(f"  Actual usage not set. Using required: {line.quantity_required}")
            qty_to_deduct = line.quantity_required
            line.quantity_used = qty_to_deduct
            line.save()
        else:
            logger.info(f"  Using actual usage: {qty_to_deduct}")

        # 2. 获取或创建【今天】的快照 (Carry Forward Logic)
        snapshot = InventorySnapshot.objects.filter(product=comp, snapshot_date=today).first()

        if snapshot:
            logger.info(f"  Found TODAY'S snapshot (ID: {snapshot.id}). Pre-update OH: {snapshot.quantity_on_hand}")
        else:
            logger.info(f"  No snapshot for today. Searching for previous record...")
            last_snapshot = InventorySnapshot.objects.filter(
                product=comp,
                snapshot_date__lt=today
            ).order_by('-snapshot_date').first()

            initial_oh = last_snapshot.quantity_on_hand if last_snapshot else Decimal('0')
            initial_reserved = last_snapshot.quantity_reserved if last_snapshot else Decimal('0')
            logger.info(f"  Found previous snapshot from {last_snapshot.snapshot_date if last_snapshot else 'N/A'}. Carry forward OH: {initial_oh}")

            snapshot = InventorySnapshot.objects.create(
                product=comp,
                snapshot_date=today,
                quantity_on_hand=initial_oh,
                quantity_reserved=initial_reserved
            )
            logger.info(f"  Created NEW snapshot for today (ID: {snapshot.id})")

        # 3. 执行扣减
        # 注意: 之前 lock 是增加了 required，所以现在释放 required
        logger.info(f"  Releasing Reserved: -{line.quantity_required}")
        logger.info(f"  Deducting On Hand: -{qty_to_deduct}")

        snapshot.quantity_reserved = F('quantity_reserved') - line.quantity_required
        snapshot.quantity_on_hand = F('quantity_on_hand') - qty_to_deduct
        snapshot.save()

    # --- B. 成品处理 (Finished Goods) ---
    fg = order.product
    fg_qty = order.quantity
    logger.info(f"--- Processing Finished Good: {fg.sku} (+{fg_qty}) ---")

    # 1. 获取或创建【今天】的成品快照
    fg_snapshot = InventorySnapshot.objects.filter(product=fg, snapshot_date=today).first()

    if fg_snapshot:
        logger.info(f"  Found TODAY'S FG snapshot (ID: {fg_snapshot.id}). Pre-update OH: {fg_snapshot.quantity_on_hand}")
    else:
        logger.info(f"  No FG snapshot for today. Searching for previous...")
        last_fg_snap = InventorySnapshot.objects.filter(
            product=fg,
            snapshot_date__lt=today
        ).order_by('-snapshot_date').first()

        initial_fg_oh = last_fg_snap.quantity_on_hand if last_fg_snap else Decimal('0')
        initial_fg_reserved = last_fg_snap.quantity_reserved if last_fg_snap else Decimal('0')
        logger.info(f"  Found previous FG snapshot. Carry forward OH: {initial_fg_oh}")

        fg_snapshot = InventorySnapshot.objects.create(
            product=fg,
            snapshot_date=today,
            quantity_on_hand=initial_fg_oh,
            quantity_reserved=initial_fg_reserved
        )
        logger.info(f"  Created NEW FG snapshot for today (ID: {fg_snapshot.id})")

    # 2. 增加成品库存
    fg_snapshot.quantity_on_hand = F('quantity_on_hand') + fg_qty
    fg_snapshot.save()
    logger.info(f"  FG Stock updated.")

    # --- C. 状态更新 ---
    order.status = 'COMPLETED'
    order.save()
    logger.info(f"=== ORDER {order.order_number} COMPLETED SUCCESSFULLY ===")
