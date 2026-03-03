import random
import decimal
import calendar
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import F

# Added ProductGroup to imports
from inventory.models import Product, BillOfMaterial, InventorySnapshot, ProductGroup
from forecast.models import ForecastEntry, MarketDemand, ForecastPlan, OutboundShipment
from production.models import ProductionOrder, ProductionComponent

class Command(BaseCommand):
    help = 'Reset Data: Aligns Simulation Date to NOW with Categorized Inventory & Groups.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear-only',
            action='store_true',
            help='Delete all data but do not repopulate it',
        )

    def handle(self, *args, **options):
        # === DATE ALIGNMENT: future-only data from today (no historical seed) ===
        today = timezone.now().date()
        self.SIMULATION_DATE = today
        self.START_DATE = today

        with transaction.atomic():
            self.clear_data()

            if options['clear_only']:
                self.stdout.write(self.style.SUCCESS('🧹 Data cleared successfully. Database is now empty.'))
                return

            self.stdout.write(self.style.WARNING('Initializing Data with Groups & Categories...'))

            # 1. Create Groups first
            self.create_product_groups()

            # 2. Create Products linked to Groups
            self.create_products()

            self.create_bom()
            self.create_inventory()
            self.create_shipments()
            self.create_production_orders()
            self.create_market_demand()

        self.stdout.write(self.style.SUCCESS('✅ Data reset complete! Inventory is now organized by Category AND Group.'))

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
        ProductGroup.objects.all().delete()  # Clear Groups

    def create_product_groups(self):
        """Create 2 distinct groups (tabs) for each nature."""
        self.stdout.write("Creating Product Groups...")
        self.group_map = {}

        # Definitions: (Nature, [Group Names])
        definitions = [
            ('FG', ['Retail Line', 'HORECA Line']),           # Finished Goods Groups
            ('RAW', ['Imported Ingredients', 'Local Sourcing']), # Raw Material Groups
            ('PKG', ['Premium Packaging', 'Standard Packaging']) # Packaging Groups
        ]

        for nature, group_names in definitions:
            for index, name in enumerate(group_names):
                pg = ProductGroup.objects.create(
                    nature=nature,
                    name=name,
                    order=index
                )
                self.group_map[name] = pg

    def create_products(self):
        self.stdout.write("Creating Products with Categories & Groups...")

        # Structure: (SKU, Name, Nature, Category, Group_Name, Unit, Usage, Safety Days)
        products = [
            # === FINISHED GOODS (FG) ===
            # Group: Retail Line
            ('FG-SYR-VAN', 'Vanilla Syrup 750ml', 'FG', 'Syrups', 'Retail Line', 'BTL', 25, 14),
            ('FG-SYR-HAZ', 'Hazelnut Syrup 750ml', 'FG', 'Syrups', 'Retail Line', 'BTL', 20, 14),

            # Group: HORECA Line (Bulk/Food Service)
            ('FG-SAU-CAR', 'Caramel Sauce 1L', 'FG', 'Sauces', 'HORECA Line', 'BTL', 15, 14),
            ('FG-SAU-COC', 'Chocolate Sauce 1L', 'FG', 'Sauces', 'HORECA Line', 'BTL', 12, 14),
            ('FG-CON-LEM', 'Lemon Tea Concentrate 1L', 'FG', 'Concentrates', 'HORECA Line', 'BTL', 28, 7),

            # === RAW MATERIALS (RAW) ===
            # Group: Local Sourcing (High Volume / Commodity)
            ('RAW-SUG-001', 'White Sugar Standard', 'RAW', 'Core Ingredients', 'Local Sourcing', 'KG', 100, 30),
            ('RAW-SUG-BRN', 'Brown Sugar Premium', 'RAW', 'Core Ingredients', 'Local Sourcing', 'KG', 20, 30),
            ('RAW-WAT-FIL', 'Filtered Water', 'RAW', 'Core Ingredients', 'Local Sourcing', 'L', 200, 3),

            # Group: Imported Ingredients (Specialty / High Value)
            ('RAW-GLU-SYR', 'Glucose Syrup', 'RAW', 'Core Ingredients', 'Imported Ingredients', 'KG', 15, 30),
            ('RAW-VAN-EXT', 'Vanilla Extract Premium', 'RAW', 'Flavor Agents', 'Imported Ingredients', 'L', 2, 60),
            ('RAW-HAZ-EXT', 'Hazelnut Extract', 'RAW', 'Flavor Agents', 'Imported Ingredients', 'L', 1.5, 60),
            ('RAW-CAR-FLV', 'Caramel Flavoring', 'RAW', 'Flavor Agents', 'Imported Ingredients', 'L', 1, 60),
            ('RAW-TEA-BLK', 'Black Tea Extract', 'RAW', 'Flavor Agents', 'Imported Ingredients', 'L', 5, 45),
            ('RAW-COC-POW', 'Cocoa Powder', 'RAW', 'Flavor Agents', 'Imported Ingredients', 'KG', 10, 30),
            ('RAW-MLK-POW', 'Milk Powder Full Cream', 'RAW', 'Additives', 'Imported Ingredients', 'KG', 10, 20),
            ('RAW-ACD-CIT', 'Citric Acid', 'RAW', 'Additives', 'Imported Ingredients', 'KG', 2, 30),

            # === PACKAGING (PKG) ===
            # Group: Premium Packaging (Glass / Specific Branding)
            ('PKG-BTL-GLS-750', 'Glass Bottle 750ml Clear', 'PKG', 'Bottles', 'Premium Packaging', 'EA', 100, 20),
            ('PKG-LAB-VAN', 'Label Vanilla 750ml', 'PKG', 'Labels', 'Premium Packaging', 'EA', 50, 30),
            ('PKG-LAB-HAZ', 'Label Hazelnut 750ml', 'PKG', 'Labels', 'Premium Packaging', 'EA', 40, 30),

            # Group: Standard Packaging (Generic / Bulk)
            ('PKG-BTL-PET-1L', 'PET Bottle 1L', 'PKG', 'Bottles', 'Standard Packaging', 'EA', 60, 20),
            ('PKG-CAP-BLK', 'Cap Black Standard', 'PKG', 'Closures', 'Standard Packaging', 'EA', 150, 20),
            ('PKG-CAP-WHT', 'Cap White Standard', 'PKG', 'Closures', 'Standard Packaging', 'EA', 80, 20),
            ('PKG-LAB-GEN', 'Label Generic Brand', 'PKG', 'Labels', 'Standard Packaging', 'EA', 100, 30),
        ]

        for sku, desc, nature, category, group_name, uom, usage, safety_days in products:
            # Fetch the pre-created group object
            group_obj = self.group_map.get(group_name)

            Product.objects.create(
                sku=sku,
                description=desc,
                nature=nature,
                category=category,
                group=group_obj,  # <--- Assigning the Group here
                uom=uom,
                unit_weight=1.0 if uom == 'KG' else 0,
                estimated_daily_usage=usage,
                safety_stock_days=safety_days
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
        """Generating Inventory Snapshots"""
        self.stdout.write("Generating Inventory Snapshots...")

        products = Product.objects.all()
        for product in products:
            daily_usage = float(product.estimated_daily_usage)
            safety_stock = daily_usage * product.safety_stock_days

            # Force shortage for specific items to demonstrate alerts
            if product.sku in ['FG-SYR-VAN', 'FG-CON-LEM']:
                qty = 0
            else:
                qty = int(safety_stock * random.uniform(0.5, 1.5))

            InventorySnapshot.objects.create(
                product=product,
                snapshot_date=self.SIMULATION_DATE,
                quantity_on_hand=max(0, qty),
                quantity_on_order=0,
                quantity_reserved=0
            )

    def create_shipments(self):
        self.stdout.write("Creating 15 Outbound Shipments...")
        self.future_shipments = []
        destinations = ['Malaysia', 'India', 'Singapore']

        for i in range(15):
            etd = self.SIMULATION_DATE + timedelta(days=random.randint(5, 150))
            dest = random.choice(destinations)
            status = 'CONFIRMED' if (etd - self.SIMULATION_DATE).days <= 14 else 'PLANNING'
            month_str = etd.strftime('%b%y').upper()
            dest_code = dest[:3].upper()
            ref = f"CONT-{month_str}-{dest_code}-{random.randint(10,99)}"

            shipment = OutboundShipment.objects.create(reference=ref, etd=etd, destination=dest, status=status)
            self.future_shipments.append(shipment)
        return self.future_shipments

    def create_production_orders(self):
        """
        Make-to-Order (MTO): Production batches are sized and scheduled to fulfill
        3-market demand. No overbuilding; each batch covers the next wave of orders.

        - Total daily outflow = estimated_daily_usage * 3 markets.
        - Monthly target = total_daily_outflow * 30.
        - 6 batches per month (one every 5 days); batch_qty = (monthly_target/6) * [1.0, 1.1].
        - First 3 orders CONFIRMED (near-term), last 3 DRAFT (planning).
        """
        self.stdout.write("Generating Production Orders...")
        today = self.SIMULATION_DATE
        fgs = list(Product.objects.filter(nature='FG'))
        if not fgs:
            return

        batches_per_month = 6
        days_between_batches = 5

        for product in fgs:
            daily_per_market = float(product.estimated_daily_usage)
            total_daily_outflow = daily_per_market * 3  # 3 markets
            monthly_target = total_daily_outflow * 30

            if monthly_target <= 0:
                continue

            base_batch_qty = monthly_target / batches_per_month

            for i in range(batches_per_month):
                start_date = today + timedelta(days=i * days_between_batches)
                # Slight buffer so production stays ahead of demand (safety stock)
                raw_qty = base_batch_qty * random.uniform(1.0, 1.1)
                qty_val = max(1, int(raw_qty))
                qty = decimal.Decimal(qty_val)

                status = 'CONFIRMED' if i < 3 else 'DRAFT'

                po = ProductionOrder.objects.create(
                    order_number=f"PO-{start_date.strftime('%y%m')}-{random.randint(1000, 9999)}",
                    product=product,
                    quantity=qty,
                    start_date=start_date,
                    status=status,
                )

                for bom in BillOfMaterial.objects.filter(product=product):
                    req_qty = bom.quantity * qty
                    ProductionComponent.objects.create(
                        production_order=po,
                        component=bom.component,
                        quantity_required=req_qty,
                        quantity_used=decimal.Decimal('0'),
                    )

    def create_market_demand(self):
        self.stdout.write("Generating Market Demand (Sales & Forecasts)...")
        random.seed(42)
        fgs = Product.objects.filter(nature='FG')
        today = self.SIMULATION_DATE
        current_month = self.START_DATE
        end_month = self.SIMULATION_DATE + relativedelta(months=6)
        markets = ['Malaysia', 'India', 'Singapore']

        while current_month < end_month:
            is_past = current_month < today
            days_into_future = (current_month - today).days

            for product in fgs:
                for country in markets:
                    daily_usage = float(product.estimated_daily_usage)
                    monthly_base = int(daily_usage * 30)

                    # 1. FORECAST (Generated exactly on current_month date)
                    seasonality = 1.2 if current_month.month in [11, 12, 1] else 1.0
                    fc_qty = min(
                        int(monthly_base * seasonality * random.uniform(1.2, 1.5)),
                        980,
                    )
                    MarketDemand.objects.create(
                        product=product,
                        period_date=current_month,
                        country=country,
                        quantity=fc_qty,
                        demand_type='FORECAST',
                        is_allocated=False,
                    )

                    # 2. ACTUAL SALES ORDERS
                    act_qty = min(
                        int(monthly_base * random.uniform(0.9, 1.15)),
                        980,
                    )
                    demand = MarketDemand(
                        product=product,
                        period_date=current_month,  # CRITICAL FIX: Must match Forecast date exactly for grouping
                        country=country,
                        quantity=act_qty,
                        demand_type='ACTUAL',
                    )

                    if is_past:
                        demand.shipped_date = current_month + relativedelta(days=28)
                        demand.is_allocated = True
                        demand.allocated_qty = act_qty
                    else:
                        demand.shipped_date = None

                        # Link to Shipment (High probability to ensure it shows up in UI)
                        # STRICT MATCH: Destination AND exact Month/Year
                        valid_shipments = [
                            s for s in getattr(self, 'future_shipments', [])
                            if s.destination == country
                            and s.etd.year == current_month.year
                            and s.etd.month == current_month.month
                        ]
                        if valid_shipments and random.random() > 0.2:  # 80% chance
                            demand.shipment = random.choice(valid_shipments)

                        # Simulate Allocation: Force allocation if it's tied to a shipment,
                        # otherwise use random chance
                        if demand.shipment or (days_into_future <= 45 and random.random() > 0.3):
                            demand.is_allocated = True
                            # If it has a shipment, allocate almost full quantity.
                            # Otherwise, random partial allocation.
                            ratio = (
                                random.uniform(0.8, 1.0)
                                if demand.shipment
                                else random.uniform(0.5, 1.0)
                            )
                            demand.allocated_qty = int(act_qty * ratio)
                        else:
                            demand.is_allocated = False
                            demand.allocated_qty = 0

                    # CRITICAL FIX: Ensure the record is saved to the database!
                    demand.save()

            current_month += relativedelta(months=1)
