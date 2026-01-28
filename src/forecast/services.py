import pandas as pd
from datetime import timedelta, date, datetime

from django.db import transaction
from django.db.models import Sum
from decimal import Decimal, InvalidOperation

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

def run_mrp_engine(target_month_date):
    """
    MRP 引擎：计算净需求
    Net Requirement = (Total Demand + Safety Stock) - (Stock On Hand + Incoming POs)
    """
    # 1. 汇总该月所有国家的 FORECAST
    demands = MarketDemand.objects.filter(
        period_date__year=target_month_date.year,
        period_date__month=target_month_date.month,
        demand_type='FORECAST'
    ).values('product').annotate(total_qty=Sum('quantity'))

    if not demands:
        return False, "该月没有预测数据 (Forecast)，请先导入 Demand。"

    plan_name = f"MRP Plan - {target_month_date.strftime('%Y-%m')} (Auto)"

    # 防止重复创建同名 Plan，先删除旧的 draft 或者报错？这里选择加时间戳后缀
    if ForecastPlan.objects.filter(name=plan_name).exists():
        plan_name = f"{plan_name} v{datetime.now().strftime('%H%M%S')}"

    entries = []
    products_bulk = Product.objects.in_bulk([d['product'] for d in demands])

    with transaction.atomic():
        plan = ForecastPlan.objects.create(name=plan_name, target_month=target_month_date)

        for item in demands:
            product = products_bulk.get(item['product'])
            if not product: continue

            forecast_qty = float(item['total_qty'])

            # --- 库存数据获取 ---
            # 假设 Product 模型里没有实时库存字段，我们需要去 InventorySnapshot 或实时计算
            # 简化版：这里假设 Product 上有一个 current_stock (需要在 View 层 annotate)
            # 或者在这里直接查 InventorySnapshot (虽然可能有延迟)
            last_snapshot = product.snapshots.order_by('-snapshot_date').first()
            soh = float(last_snapshot.quantity_on_hand) if last_snapshot else 0

            # --- 安全库存计算 ---
            # Safety Stock = (月销量 / 30) * 安全天数
            daily_usage = forecast_qty / 30
            safety_stock = daily_usage * product.safety_stock_days

            # --- 净需求公式 ---
            projected_balance = soh - forecast_qty

            if projected_balance < safety_stock:
                # 缺口 = 安全库存 - 预计结余
                shortage = safety_stock - projected_balance

                # 考虑 MOQ (最小起订量)
                suggested_qty = max(shortage, float(product.moq))

                # 计算时间 (倒推 Lead Time)
                # 假设需要在月头这就准备好
                start_date = target_month_date - timedelta(days=product.lead_time_days)

                note = f"Forecast: {forecast_qty:.0f}, SOH: {soh:.0f}, SS: {safety_stock:.0f}"

                entries.append(ForecastEntry(
                    plan=plan,
                    product=product,
                    suggested_qty=suggested_qty,
                    eta_date=target_month_date,
                    suggested_start_date=start_date,
                    calculation_note=note
                ))

        ForecastEntry.objects.bulk_create(entries)

    return True, f"MRP 运行完成，生成 {len(entries)} 条生产建议。"

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
