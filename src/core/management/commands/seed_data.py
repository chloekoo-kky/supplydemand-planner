import random
import decimal
import calendar
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import F

from inventory.models import Product, BillOfMaterial, InventorySnapshot
from forecast.models import ForecastEntry, MarketDemand, ForecastPlan, OutboundShipment
from production.models import ProductionOrder, ProductionComponent
# Import services to trigger the logic
from production.services import calculate_requirements, lock_stock_for_order, complete_production

class Command(BaseCommand):
    help = 'Reset Data: Aligns Simulation Date to NOW, includes Future Actuals, and keeps demand < 1000.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('Initializing Demo Data...'))

        # === DATE ALIGNMENT FIX ===
        # Set Simulation Date to TODAY so that UI operations (which use today)
        # match the inventory snapshots.
        today = timezone.now().date()
        self.SIMULATION_DATE = today

        # Start history 6 months ago
        self.START_DATE = today - relativedelta(months=6)

        self.stdout.write(f"📅 Simulation Date (Today): {self.SIMULATION_DATE}")
        self.stdout.write(f"📅 History Start Date: {self.START_DATE}")

        with transaction.atomic():
            self.clear_data()
            self.create_products()
            self.create_bom()
            self.create_inventory()
            self.create_shipments()
            self.create_production_orders()
            self.create_market_demand()

        self.stdout.write(self.style.SUCCESS('✅ Data reset complete! Ready for manual testing.'))

    def clear_data(self):
        self.stdout.write("Clearing old data...")
        ProductionComponent.objects.all().delete()
        ProductionOrder.objects.all().delete()
        ForecastEntry.objects.all().delete()
        ForecastPlan.objects.all().delete()
        MarketDemand.objects.all().delete()
        OutboundShipment.objects.all().delete()
        InventorySnapshot.objects.all().delete()
        BillOfMaterial.objects.all().delete()
        Product.objects.all().delete()

    def create_products(self):
        self.stdout.write("Creating Products (with reduced usage)...")
        # UPDATED: Reduced 'estimated_daily_usage' to ensure monthly demand < 1000
        # e.g., 25 * 30 days = 750 (max)
        products = [
            ('FG-SYR-VAN', 'Vanilla Syrup 750ml', 'FG', 'BTL', 25, 14), # Reduced from 50
            ('FG-SYR-HAZ', 'Hazelnut Syrup 750ml', 'FG', 'BTL', 20, 14), # Reduced from 40
            ('FG-SAU-CAR', 'Caramel Sauce 1L', 'FG', 'BTL', 15, 14),    # Reduced from 30
            ('FG-SAU-COC', 'Chocolate Sauce 1L', 'FG', 'BTL', 12, 14),  # Reduced from 25
            ('FG-CON-LEM', 'Lemon Tea Concentrate 1L', 'FG', 'BTL', 28, 7), # Reduced from 60
            ('RAW-SUG-001', 'White Sugar Standard', 'RAW', 'KG', 100, 30),
            ('RAW-WAT-FIL', 'Filtered Water', 'RAW', 'L', 200, 3),
            ('RAW-VAN-EXT', 'Vanilla Extract Premium', 'RAW', 'L', 2, 60),
            ('RAW-HAZ-EXT', 'Hazelnut Extract', 'RAW', 'L', 1.5, 60),
            ('RAW-COC-POW', 'Cocoa Powder', 'RAW', 'KG', 10, 30),
            ('RAW-GLU-SYR', 'Glucose Syrup', 'RAW', 'KG', 15, 30),
            ('RAW-SUG-BRN', 'Brown Sugar Premium', 'RAW', 'KG', 20, 30),
            ('RAW-MLK-POW', 'Milk Powder Full Cream', 'RAW', 'KG', 10, 20),
            ('RAW-CAR-FLV', 'Caramel Flavoring', 'RAW', 'L', 1, 60),
            ('RAW-TEA-BLK', 'Black Tea Extract', 'RAW', 'L', 5, 45),
            ('RAW-ACD-CIT', 'Citric Acid', 'RAW', 'KG', 2, 30),
            ('PKG-BTL-GLS-750', 'Glass Bottle 750ml Clear', 'PKG', 'EA', 100, 20),
            ('PKG-CAP-BLK', 'Cap Black Standard', 'PKG', 'EA', 150, 20),
            ('PKG-LAB-VAN', 'Label Vanilla 750ml', 'PKG', 'EA', 50, 30),
            ('PKG-BTL-PET-1L', 'PET Bottle 1L', 'PKG', 'EA', 60, 20),
            ('PKG-CAP-WHT', 'Cap White Standard', 'PKG', 'EA', 80, 20),
            ('PKG-LAB-HAZ', 'Label Hazelnut 750ml', 'PKG', 'EA', 40, 30),
            ('PKG-LAB-GEN', 'Label Generic Brand', 'PKG', 'EA', 100, 30),
        ]

        for sku, desc, nature, uom, usage, safety_days in products:
            Product.objects.create(
                sku=sku, description=desc, nature=nature, uom=uom,
                unit_weight=1.0 if uom == 'KG' else 0,
                estimated_daily_usage=usage, safety_stock_days=safety_days
            )

    def create_bom(self):
        self.stdout.write("Building BOMs...")
        recipes = [
            ('FG-SYR-VAN', [('RAW-SUG-001', 0.8), ('RAW-WAT-FIL', 0.5), ('RAW-VAN-EXT', 0.02), ('PKG-BTL-GLS-750', 1), ('PKG-CAP-BLK', 1), ('PKG-LAB-VAN', 1)]),
            ('FG-SYR-HAZ', [('RAW-SUG-001', 0.75), ('RAW-WAT-FIL', 0.55), ('RAW-HAZ-EXT', 0.025), ('PKG-BTL-GLS-750', 1), ('PKG-CAP-WHT', 1), ('PKG-LAB-HAZ', 1)]),
            ('FG-SAU-COC', [('RAW-SUG-001', 0.5), ('RAW-COC-POW', 0.15), ('RAW-GLU-SYR', 0.2), ('PKG-BTL-PET-1L', 1), ('PKG-CAP-BLK', 1), ('PKG-LAB-GEN', 1)]),
            ('FG-SAU-CAR', [('RAW-SUG-BRN', 0.6), ('RAW-GLU-SYR', 0.2), ('RAW-MLK-POW', 0.1), ('RAW-CAR-FLV', 0.02), ('PKG-BTL-PET-1L', 1), ('PKG-CAP-BLK', 1), ('PKG-LAB-GEN', 1)]),
            ('FG-CON-LEM', [('RAW-TEA-BLK', 0.1), ('RAW-ACD-CIT', 0.05), ('RAW-SUG-001', 0.4), ('RAW-WAT-FIL', 0.45), ('PKG-BTL-PET-1L', 1), ('PKG-CAP-WHT', 1), ('PKG-LAB-GEN', 1)]),
        ]

        for parent_sku, components in recipes:
            try:
                parent_obj = Product.objects.get(sku=parent_sku)
                for comp_sku, qty in components:
                    try:
                        component_obj = Product.objects.get(sku=comp_sku)
                        BillOfMaterial.objects.create(product=parent_obj, component=component_obj, quantity=qty)
                    except Product.DoesNotExist: pass
            except Product.DoesNotExist: pass

    def create_inventory(self):
        """生成库存快照"""
        self.stdout.write("Generating Inventory Snapshots...")

        products = Product.objects.all()
        for product in products:
            daily_usage = float(product.estimated_daily_usage)
            safety_stock = daily_usage * product.safety_stock_days

            # 【强制缺货逻辑】
            if product.sku in ['FG-SYR-VAN', 'FG-CON-LEM']:
                qty = 0
            else:
                qty = int(safety_stock * random.uniform(0.5, 1.5))

            # Create snapshot for TODAY
            InventorySnapshot.objects.create(
                product=product,
                snapshot_date=self.SIMULATION_DATE,
                quantity_on_hand=max(0, qty),
                quantity_on_order=0,
                quantity_reserved=0
            )

    def create_shipments(self):
        """Create sample shipments relative to current date"""
        self.stdout.write("Creating Outbound Shipments...")

        base_date = self.SIMULATION_DATE

        def get_ref(dt, dest):
            month_str = dt.strftime('%b%y').upper()
            dest_code = dest[:3].upper() if dest else "OTH"
            return f"CONT-{month_str}-{dest_code}-01"

        dates = [
            (base_date - relativedelta(months=1), 'Malaysia'),
            (base_date + relativedelta(days=10), 'India'), # Coming up soon
            (base_date + relativedelta(months=1), 'Malaysia'),
        ]

        for ship_date, dest in dates:
            OutboundShipment.objects.create(
                reference=get_ref(ship_date, dest),
                etd=ship_date,
                destination=dest,
                status='PLANNING'
            )

    def create_production_orders(self):
        """Generating Production Orders (8+ per month, DRAFT)"""
        self.stdout.write("Generating Production Orders...")
        fgs = list(Product.objects.filter(nature='FG'))
        if not fgs: return

        # REFACTORED: Start generating orders from the Simulation Date (February)
        # instead of the historical START_DATE (August).
        current_month = self.SIMULATION_DATE

        # Keep the 6-month horizon for future orders
        end_month = self.SIMULATION_DATE + relativedelta(months=6)

        while current_month < end_month:
            orders_count = random.randint(8, 12)
            _, days_in_month = calendar.monthrange(current_month.year, current_month.month)

            for _ in range(orders_count):
                product = random.choice(fgs)
                # Reduced Order Quantity to match lower usage (20-100 range)
                qty = decimal.Decimal(random.randint(20, 100))
                random_day = random.randint(1, days_in_month)

                # Ensure we don't crash if the random day is invalid for the month (handled by monthrange, but good practice)
                try:
                    start_date = current_month.replace(day=random_day)
                except ValueError:
                    start_date = current_month.replace(day=days_in_month)

                po = ProductionOrder.objects.create(
                    order_number=f"PO-{start_date.strftime('%y%m')}-{random.randint(1000,9999)}",
                    product=product, quantity=qty, start_date=start_date, status='DRAFT'
                )

                for bom in BillOfMaterial.objects.filter(product=product):
                    req_qty = bom.quantity * qty
                    ProductionComponent.objects.create(
                        production_order=po, component=bom.component, quantity_required=req_qty, quantity_used=0
                    )

            current_month += relativedelta(months=1)

    def create_market_demand(self):
        """生成市场需求 (Forecast + Actual Sales Orders)"""
        self.stdout.write("Generating Market Demand (Values capped < 1000)...")
        random.seed(42)
        fgs = Product.objects.filter(nature='FG')

        current_month = self.START_DATE
        end_month = self.SIMULATION_DATE + relativedelta(months=6)

        markets = ['Malaysia', 'India']

        while current_month < end_month:
            for product in fgs:
                for country in markets:
                    daily_usage = float(product.estimated_daily_usage)
                    monthly_base = int(daily_usage * 30)

                    # --- 1. FORECAST ---
                    # Removed "High Demand" 3000 logic for Vanilla Syrup
                    seasonality = 1.2 if current_month.month in [11, 12, 1] else 1.0
                    variance_fc = random.uniform(1.2, 1.5)
                    fc_qty = int(monthly_base * seasonality * variance_fc)

                    # SAFETY CAP: Ensure < 1000
                    fc_qty = min(fc_qty, 980)

                    MarketDemand.objects.create(
                        product=product,
                        period_date=current_month,
                        country=country,
                        quantity=fc_qty,
                        demand_type='FORECAST'
                    )

                    # --- 2. ACTUAL SALES ORDERS ---
                    # Logic: Generate actuals for Past (History) AND Future (Confirmed Orders)
                    variance_act = random.uniform(0.9, 1.15)
                    act_qty = int(monthly_base * variance_act)

                    # SAFETY CAP: Ensure < 1000
                    act_qty = min(act_qty, 980)

                    MarketDemand.objects.create(
                        product=product,
                        period_date=current_month,
                        country=country,
                        quantity=act_qty,
                        demand_type='ACTUAL',
                        shipment=None,
                        allocated_qty=0,
                        is_allocated=False
                    )

            current_month += relativedelta(months=1)
