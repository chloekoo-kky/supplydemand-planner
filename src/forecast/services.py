import pandas as pd
import json
from datetime import timedelta, date, datetime
from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.db.models import Sum, F, Q
from decimal import Decimal, InvalidOperation
from django.utils import timezone

from inventory.models import Product, ProductAlias
from production.models import ProductionOrder
from .models import MarketDemand, ForecastPlan, ForecastEntry, OutboundShipment

def process_demand_file(file_obj, country, demand_type='FORECAST'):
    """
    导入逻辑升级：支持“宽表” (SKU, Jan, Feb, Mar...)
    """
    try:
        if file_obj.name.endswith('.csv'):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)
    except Exception as e:
        return False, [f"文件读取失败: {str(e)}"]

    # 1. 清理列名 (全小写，去空格)
    # 但要注意，如果是日期列名，可能需要特殊处理，这里先转字符串
    df.columns = [str(c).strip() for c in df.columns]

    # 2. 找到 SKU 列
    # 允许用户写 'sku', 'product code', 'item' 等
    sku_col = next((c for c in df.columns if c.lower() in ['sku', 'product', 'code']), None)
    if not sku_col:
        return False, ["找不到 'SKU' 列，请检查表头。"]

    products_map = {p.sku.upper(): p for p in Product.objects.filter(nature='FG')}

    errors = []
    imported_count = 0

    with transaction.atomic():
        for _, row in df.iterrows():
            sku_val = str(row[sku_col]).strip().upper()
            product = products_map.get(sku_val)

            if not product:
                # 也可以尝试查 Alias，这里省略
                continue

            # 3. 遍历所有列，寻找“日期列”
            # 逻辑：只要列名能被解析为日期 (YYYY-MM, Jan-25, etc.)，就是需求数据
            for col in df.columns:
                if col == sku_col: continue

                try:
                    # 尝试解析列名为日期
                    # pd.to_datetime 非常强大，能识别 "2026-01", "Jan 2026", "2026/01"
                    period_date = pd.to_datetime(col).date().replace(day=1)
                except:
                    # 不是日期列，跳过 (可能是 Description 等)
                    continue

                # 读取数量
                try:
                    qty = float(row[col])
                except:
                    qty = 0

                if qty > 0:
                    MarketDemand.objects.update_or_create(
                        period_date=period_date,
                        country=country,
                        product=product,
                        demand_type=demand_type,
                        defaults={'quantity': qty}
                    )
                    imported_count += 1

    return True, f"成功导入 {imported_count} 条需求数据 ({country} - {demand_type})。"


def calculate_mrp_logic(product, target_month_date):
    """
    Core MRP Math isolated for a single product.
    Refactored to use STRICT MONTHLY BUCKETS for both Demand and Supply.
    Excludes Backlog (past demand) and Late Supply (past due POs).
    """
    target_month_date = target_month_date.replace(day=1)

    months_horizon = [
        target_month_date,
        target_month_date + relativedelta(months=1),
        target_month_date + relativedelta(months=2)
    ]

    # 1. Initial Stock
    last_snapshot = product.snapshots.order_by('-snapshot_date').first()
    current_soh = float(last_snapshot.quantity_on_hand) if last_snapshot else 0.0

    real_reserved = MarketDemand.objects.filter(
        product=product,
        is_allocated=True,
        shipped_date__isnull=True
    ).aggregate(t=Sum('allocated_qty'))['t'] or 0.0

    current_reserved = float(real_reserved)
    running_balance = current_soh - current_reserved

    breakdown_data = {
        "initial_stock": running_balance,
        "months": []
    }

    target_month_shortage = 0.0

    # 2. Rolling Calculation
    for i, month_date in enumerate(months_horizon):
        # Base Queries
        base_demand_query = Q(product=product, shipped_date__isnull=True)
        # Supply includes DRAFT now
        base_supply_query = Q(
            product=product,
            status__in=['DRAFT', 'CONFIRMED', 'IN_PROGRESS']
        )

        # === REFACTORED SECTIONS START ===
        # Use exact month matching for ALL months (including the first one).
        # This ensures we only look at what is scheduled specifically for this month.

        # A. Demand Filter (Strict Month Match)
        time_filter_demand = Q(
            period_date__year=month_date.year,
            period_date__month=month_date.month
        )

        # B. Supply Filter (Strict Month Match)
        time_filter_supply = Q(
            due_date__year=month_date.year,
            due_date__month=month_date.month
        )
        # === REFACTORED SECTIONS END ===

        # A. Demand (Actuals Only as requested previously, or maintain logic)
        current_demand_qs = MarketDemand.objects.filter(base_demand_query & time_filter_demand)
        sum_stats = current_demand_qs.aggregate(
            total_forecast=Sum('quantity', filter=Q(demand_type='FORECAST')),
            total_actual=Sum('quantity', filter=Q(demand_type='ACTUAL')),
            total_alloc=Sum('allocated_qty')
        )

        sum_forecast = float(sum_stats['total_forecast'] or 0.0)
        sum_actual = float(sum_stats['total_actual'] or 0.0)
        total_allocated = float(sum_stats['total_alloc'] or 0.0)

        total_demand = sum_actual # MRP Policy: Actuals Only
        gross_requirement = max(0, total_demand - total_allocated)

        # B. Supply
        inbound_agg = ProductionOrder.objects.filter(
            base_supply_query & time_filter_supply
        ).aggregate(total=Sum('quantity'))
        projected_inbound = float(inbound_agg['total'] or 0.0)

        # C. Balance
        end_balance = running_balance + projected_inbound - gross_requirement

        month_data = {
            "month": month_date.strftime('%Y-%m'),
            "demand": round(total_demand, 0),
            "demand_forecast": round(sum_forecast, 0),
            "allocated": round(total_allocated, 0),
            "gross_req": round(gross_requirement, 0),
            "inbound": round(projected_inbound, 0),
            "balance": round(end_balance, 0),
        }
        breakdown_data["months"].append(month_data)

        if i == 0 and end_balance < 0:
            target_month_shortage = abs(end_balance)

        running_balance = end_balance

    # 3. Result
    if target_month_shortage > 0:
        moq = float(product.moq or 0.0)
        suggested_qty = max(target_month_shortage, moq)
        lead_time = getattr(product, 'lead_time_days', 0)
        start_date = target_month_date - timedelta(days=lead_time)

        return {
            "suggested_qty": round(suggested_qty, 0),
            "eta_date": target_month_date,
            "suggested_start_date": start_date,
            "calculation_note": json.dumps(breakdown_data)
        }

    return {
        "suggested_qty": 0,
        "eta_date": target_month_date,
        "suggested_start_date": target_month_date,
        "calculation_note": json.dumps(breakdown_data)
    }

# === Update run_mrp_engine to use the helper ===
def run_mrp_engine(target_month_date):
    """
    Standard MRP Engine: Regenerates the entire plan.
    """
    target_month_date = target_month_date.replace(day=1)
    plan_name = f"MRP Plan - {target_month_date.strftime('%Y-%m')}"
    products = Product.objects.filter(nature='FG')
    entries = []

    with transaction.atomic():
        ForecastPlan.objects.filter(name=plan_name).delete()
        plan = ForecastPlan.objects.create(name=plan_name, target_month=target_month_date)

        for product in products:
            result = calculate_mrp_logic(product, target_month_date)
            if result and result['suggested_qty'] > 0:
                entries.append(ForecastEntry(
                    plan=plan,
                    product=product,
                    suggested_qty=result['suggested_qty'],
                    eta_date=result['eta_date'],
                    suggested_start_date=result['suggested_start_date'],
                    calculation_note=result['calculation_note']
                ))

        if entries:
            ForecastEntry.objects.bulk_create(entries)

    return True, f"MRP Complete. Updated Plan: {plan_name}"

# === Add new function for Single Entry Refresh ===
def refresh_single_entry_logic(entry_id):
    try:
        entry = ForecastEntry.objects.select_related('product', 'plan').get(pk=entry_id)
    except ForecastEntry.DoesNotExist:
        return False, "Entry not found."

    target_month = entry.plan.target_month
    result = calculate_mrp_logic(entry.product, target_month)

    if result:
        entry.suggested_qty = result['suggested_qty']
        entry.eta_date = result['eta_date']
        entry.suggested_start_date = result['suggested_start_date']
        entry.calculation_note = result['calculation_note']
        entry.save()
        return True, f"Updated {entry.product.sku}: New Qty {entry.suggested_qty}"
    else:
        # Should not happen given logic, but safe fallback
        return False, "Calculation failed."


def convert_entries_to_orders(entry_ids):
    converted_count = 0
    with transaction.atomic():
        entries = ForecastEntry.objects.filter(id__in=entry_ids, production_order__isnull=True)
        for entry in entries:
            order_no = f"PO-{date.today():%y%m%d}-{entry.id}"
            po = ProductionOrder.objects.create(
                order_number=order_no,
                product=entry.product,
                quantity=entry.suggested_qty,
                start_date=entry.suggested_start_date,
                due_date=entry.eta_date,
                status='DRAFT',
                notes=f"Converted from Plan: {entry.plan.name}"
            )
            entry.production_order = po
            entry.save()
            converted_count += 1
    return converted_count

def allocate_stock_for_demand(demand_id, request_qty, shipment_id=None):
    with transaction.atomic():
        try:
            demand = MarketDemand.objects.select_related('product').select_for_update().get(pk=demand_id)
        except MarketDemand.DoesNotExist:
            return False, "Demand record not found."

        if demand.demand_type != 'ACTUAL':
            return False, "Only 'Actual Sales' can be allocated."

        if demand.shipped_date:
            return False, "Cannot edit allocation: Item already shipped."

        try:
            new_alloc_qty = Decimal(str(request_qty))
            if new_alloc_qty < 0: raise ValueError
        except:
            return False, "Invalid allocation quantity."

        if new_alloc_qty > demand.quantity:
            return False, f"Cannot allocate {new_alloc_qty} (Max Demand: {demand.quantity})."

        if shipment_id:
            try:
                shipment = OutboundShipment.objects.get(pk=shipment_id)
                if shipment.destination:
                    ship_dest = shipment.destination.strip().lower()
                    demand_dest = demand.country.strip().lower()
                    if ship_dest != demand_dest:
                        return False, f"Error: Container '{shipment.reference}' is restricted to {shipment.destination}. This item is for {demand.country}."
                demand.shipment = shipment
            except OutboundShipment.DoesNotExist:
                return False, "Selected shipment does not exist."
        elif shipment_id == "":
            demand.shipment = None

        snapshot = demand.product.snapshots.select_for_update().order_by('-snapshot_date').first()
        if not snapshot:
            return False, f"No inventory snapshot found for {demand.product.sku}."

        delta = new_alloc_qty - demand.allocated_qty

        if delta > 0:
            available_qty = snapshot.quantity_on_hand - snapshot.quantity_reserved
            if available_qty < delta:
                return False, f"Insufficient stock. Available: {available_qty:g}, Need: {delta:g}"

        snapshot.quantity_reserved += delta
        snapshot.save()

        demand.allocated_qty = new_alloc_qty
        demand.is_allocated = (new_alloc_qty > 0)
        demand.save()

    return True, f"Allocation updated. Reserved: {new_alloc_qty:g} units."


def convert_entries_to_orders(entry_ids):
    """
    [New] 将用户选定的 ForecastEntry 转换为 ProductionOrder (Draft)
    """
    converted_count = 0
    with transaction.atomic():
        # 获取未转换的 entries
        entries = ForecastEntry.objects.filter(id__in=entry_ids, production_order__isnull=True)

        for entry in entries:
            order_no = f"PO-{date.today():%y%m%d}-{entry.id}"
            po = ProductionOrder.objects.create(
                order_number=order_no,
                product=entry.product,
                quantity=entry.suggested_qty,
                start_date=entry.suggested_start_date,
                due_date=entry.eta_date,
                status='DRAFT',
                notes=f"Converted from Plan: {entry.plan.name}"
            )
            entry.production_order = po
            entry.save()
            converted_count += 1

    return converted_count

def create_po_from_plan(plan_id):
    """
    将 ForecastPlan 批量转为 Draft ProductionOrder
    """
    plan = ForecastPlan.objects.get(pk=plan_id)
    count = 0

    with transaction.atomic():
        # 只处理还没转过的
        entries = plan.entries.filter(production_order__isnull=True)

        for entry in entries:
            # 生成 PO 单号
            order_no = f"PO-{date.today():%y%m%d}-{entry.id}"

            po = ProductionOrder.objects.create(
                order_number=order_no,
                product=entry.product,
                quantity=entry.suggested_qty,
                start_date=entry.suggested_start_date,
                due_date=entry.eta_date,
                status='DRAFT', # 默认为草稿
                notes=f"Auto-generated from MRP: {plan.name}. {entry.calculation_note}"
            )

            # 回填关联
            entry.production_order = po
            entry.save()
            count += 1

        plan.is_locked = True # 锁住计划
        plan.save()

    return f"成功生成 {count} 张生产工单 (Draft)。"


def allocate_stock_for_demand(demand_id, request_qty, shipment_id=None):
    """
    [Updated] Validates Destination Match before assignment.
    """
    with transaction.atomic():
        try:
            demand = MarketDemand.objects.select_related('product').select_for_update().get(pk=demand_id)
        except MarketDemand.DoesNotExist:
            return False, "Demand record not found."

        if demand.demand_type != 'ACTUAL':
            return False, "Only 'Actual Sales' can be allocated."

        if demand.shipped_date:
            return False, "Cannot edit allocation: Item already shipped."

        try:
            new_alloc_qty = Decimal(str(request_qty))
            if new_alloc_qty < 0: raise ValueError
        except:
            return False, "Invalid allocation quantity."

        if new_alloc_qty > demand.quantity:
            return False, f"Cannot allocate {new_alloc_qty} (Max Demand: {demand.quantity})."

        # Handle Shipment Assignment
        if shipment_id:
            try:
                shipment = OutboundShipment.objects.get(pk=shipment_id)

                # [NEW Validation Logic]
                # If shipment has a specific destination, the demand's country must match it.
                if shipment.destination:
                    # Case-insensitive comparison
                    ship_dest = shipment.destination.strip().lower()
                    demand_dest = demand.country.strip().lower()

                    if ship_dest != demand_dest:
                        return False, f"Error: Container '{shipment.reference}' is restricted to {shipment.destination}. This item is for {demand.country}."

                demand.shipment = shipment
            except OutboundShipment.DoesNotExist:
                return False, "Selected shipment does not exist."
        elif shipment_id == "":
            demand.shipment = None

        # Check Stock
        snapshot = demand.product.snapshots.select_for_update().order_by('-snapshot_date').first()
        if not snapshot:
            return False, f"No inventory snapshot found for {demand.product.sku}."

        delta = new_alloc_qty - demand.allocated_qty

        if delta > 0:
            available_qty = snapshot.quantity_on_hand - snapshot.quantity_reserved
            if available_qty < delta:
                return False, f"Insufficient stock. Available: {available_qty:g}, Need: {delta:g}"

        snapshot.quantity_reserved += delta
        snapshot.save()

        demand.allocated_qty = new_alloc_qty
        demand.is_allocated = (new_alloc_qty > 0)
        demand.save()

    return True, f"Allocation updated. Reserved: {new_alloc_qty:g} units."


def ship_allocated_demand(demand_id, shipment_date):
    """
    [Updated] Ship the EXACT allocated amount.
    """
    try:
        demand = MarketDemand.objects.select_related('product').get(pk=demand_id)
    except MarketDemand.DoesNotExist:
        return False, "Demand record not found."

    if demand.allocated_qty <= 0:
        return False, "No stock allocated to ship."

    if demand.shipped_date:
        return False, "Item is already shipped."

    snapshot = demand.product.snapshots.order_by('-snapshot_date').first()

    with transaction.atomic():
        # Deduct the ALLOCATED amount from On Hand and Reserved
        qty_to_ship = float(demand.allocated_qty)

        snapshot.quantity_on_hand -= qty_to_ship
        snapshot.quantity_reserved -= qty_to_ship
        snapshot.save()

        demand.is_allocated = False
        demand.shipped_date = shipment_date
        demand.save()

    return True, f"Shipped {qty_to_ship:g} units."


def auto_allocate_backlog(product):
    """
    当有新库存入库时调用。
    自动查找该产品所有 Allocated < Total Quantity 的实际订单(Actual Demand)，
    并按日期顺序自动分配现有库存。
    """
    # 1. 获取当前可用库存
    snapshot = product.snapshots.order_by('-snapshot_date').first()
    if not snapshot: return

    available_stock = snapshot.quantity_on_hand - snapshot.quantity_reserved
    if available_stock <= 0: return

    # 2. 查找积压订单 (Backlog): 类型为ACTUAL, 未完全分配, 按日期排序(FIFO)
    backlog_demands = MarketDemand.objects.filter(
        product=product,
        demand_type='ACTUAL',
        shipped_date__isnull=True, # 未发货
        allocated_qty__lt=F('quantity') # 分配量 < 需求量
    ).order_by('period_date', 'created_at') # 优先满足旧订单

    with transaction.atomic():
        for demand in backlog_demands:
            if available_stock <= 0: break

            needed = demand.quantity - demand.allocated_qty

            # 能够分配的数量
            allocatable = min(available_stock, needed)

            # 更新 Demand
            demand.allocated_qty += allocatable
            demand.is_allocated = True
            demand.save()

            # 更新 Inventory
            snapshot.quantity_reserved += allocatable
            snapshot.save() # 注意: quantity_on_hand 不变，只是 reserved 增加

            available_stock -= allocatable

            print(f"Auto-allocated {allocatable} units to Demand {demand.id} ({demand.country})")
