import random
import json
import re
import csv
import pandas as pd
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required

from django.db.models import (
    Case, When, Sum, F, Subquery, OuterRef,
    Q, Sum, Value, DecimalField, BooleanField
)
from django.db.models.functions import Coalesce
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from collections import defaultdict
from datetime import timedelta
from django.core.paginator import Paginator

from rapidfuzz import process, fuzz
from decimal import Decimal

from .models import (
    Product, ProductGroup, InventorySnapshot,
    ProductAlias, Supplier, BillOfMaterial
)
from production.models import ProductionOrder, ProductionComponent
from .services import extract_data_from_file

COLUMN_MAPPING = {
    'sku': ['sku', 'item_code', 'product_id', 'part_number', 'p/n', 'id', 'product sku', 'sku code'],
    'name': ['name', 'product_name', 'item_name', 'title', 'description', 'product', 'item description'],
    'category': ['category', 'cat', 'group', 'family', 'product category'],
    'nature': ['nature', 'material type', 'material_type', 'type'],
    'quantity': ['quantity', 'qty', 'stock', 'count', 'on_hand', 'inventory', 'total quantity'],
    'unit': ['unit', 'uom', 'measure', 'unit_of_measure'],
    'location': ['location', 'warehouse', 'bin', 'shelf', 'rack'],
    'min_stock': ['min_stock', 'minimum_stock', 'safety_stock', 'reorder_point', 'min_qty'],
    'cost': ['cost', 'price', 'unit_cost', 'buying_price', 'purchase_price', 'cost price'],
    'supplier': ['supplier', 'vendor', 'provider'],
    'moq': ['moq', 'min_order_qty', 'minimum_order', 'mq'],
    'lead_time': ['lead_time', 'lead_time_days', 'lt', 'lead_days', 'lead time (days)', 'lead time'],
    'daily_usage': ['daily_usage', 'usage', 'burn_rate', 'daily_consumption', 'estimated_daily_usage'],
    'weight': ['weight', 'unit_weight', 'kg', 'unit weight (kg)', 'wgt', 'wgt (kg)'],
    'volume': ['volume', 'unit_volume', 'vol', 'liter', 'unit volume (l)']
}

def normalize_columns(df):
    """
    Standardizes column names based on COLUMN_MAPPING.
    """
    # Clean headers: Use Regex to handle newlines (\n) and multiple spaces
    df.columns = [re.sub(r'\s+', ' ', str(col)).strip().lower() for col in df.columns]

    new_columns = {}
    for col in df.columns:
        for standard_field, aliases in COLUMN_MAPPING.items():
            if col == standard_field.replace('_', ' ') or col in aliases:
                new_columns[col] = standard_field
                break

    if new_columns:
        df = df.rename(columns=new_columns)

    return df

@login_required
def download_import_template(request):
    response = HttpResponse(
        content_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="inventory_import_template.csv"'},
    )
    writer = csv.writer(response)
    headers = ['SKU', 'Name', 'Category', 'Quantity', 'Unit', 'Location', 'Min Stock', 'Cost']
    writer.writerow(headers)
    writer.writerow(['EX-001', 'Example Product', 'Raw Material', '100', 'PCS', 'Shelf A-01', '10', '5.00'])
    return response

@login_required
def inventory_list(request, nature_code=None):
    nature_code = nature_code.upper() if nature_code else 'RAW'

    # Status Definitions
    STATUS_HARD_WIP = ['CONFIRMED', 'IN_PROGRESS']
    STATUS_SOFT_DRAFT = ['DRAFT']
    STATUS_ACTIVE = STATUS_HARD_WIP + STATUS_SOFT_DRAFT

    # --- 1. Base QuerySet ---
    latest_stock = InventorySnapshot.objects.filter(
        product=OuterRef('pk')
    ).order_by('-snapshot_date')

    fg_wip_qs = ProductionOrder.objects.filter(
        product=OuterRef('pk'),
        status__in=STATUS_HARD_WIP
    ).values('product').annotate(total=Sum('quantity')).values('total')

    fg_draft_qs = ProductionOrder.objects.filter(
        product=OuterRef('pk'),
        status__in=STATUS_SOFT_DRAFT
    ).values('product').annotate(total=Sum('quantity')).values('total')

    rm_draft_qs = ProductionComponent.objects.filter(
        component=OuterRef('pk'),
        production_order__status__in=STATUS_SOFT_DRAFT
    ).values('component').annotate(total=Sum('quantity_required')).values('total')

    all_products_qs = Product.objects.filter(nature=nature_code).select_related('supplier').annotate(
        qty_on_hand=Coalesce(Subquery(latest_stock.values('quantity_on_hand')[:1]), Value(0, output_field=DecimalField())),
        qty_reserved=Coalesce(Subquery(latest_stock.values('quantity_reserved')[:1]), Value(0, output_field=DecimalField())),
        qty_fg_wip=Coalesce(Subquery(fg_wip_qs[:1]), Value(0, output_field=DecimalField())),
        qty_fg_draft=Coalesce(Subquery(fg_draft_qs[:1]), Value(0, output_field=DecimalField())),
        qty_rm_draft=Coalesce(Subquery(rm_draft_qs[:1]), Value(0, output_field=DecimalField())),
    )

    # Calculate Net Available & Projected Stock
    all_products_qs = all_products_qs.annotate(
        net_available=Case(
            When(nature='FG', then=F('qty_on_hand') - F('qty_reserved') + F('qty_fg_wip')),
            default=F('qty_on_hand') - F('qty_reserved'),
            output_field=DecimalField()
        ),
        projected_stock=Case(
            When(nature='FG', then=F('qty_on_hand') - F('qty_reserved') + F('qty_fg_wip') + F('qty_fg_draft')),
            default=F('qty_on_hand') - F('qty_reserved') - F('qty_rm_draft'),
            output_field=DecimalField()
        )
    )

    # --- Search & Filter ---
    search_query = request.GET.get('search', '').strip()
    category_filter = request.GET.get('category', '').strip()

    if search_query:
        all_products_qs = all_products_qs.filter(
            Q(sku__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(aliases__alias_name__icontains=search_query)
        ).distinct()

    if category_filter:
        all_products_qs = all_products_qs.filter(category=category_filter)

    # Sort
    all_products_qs = all_products_qs.order_by('-is_temporary', 'sort_order', 'sku')

    # === MRP / Purchasing Action Plan ===
    products_list = list(all_products_qs)
    today = timezone.now().date()

    # 1. Batch fetch demand (Demand Map)
    demand_map = defaultdict(list)

    if nature_code in ['RAW', 'PKG']:
        active_components = ProductionComponent.objects.filter(
            production_order__status__in=STATUS_ACTIVE,
            component__nature=nature_code
        ).values(
            'component_id',
            'production_order__start_date',
            'quantity_required'
        )

        for item in active_components:
            demand_map[item['component_id']].append({
                'date': item['production_order__start_date'],
                'qty': float(item['quantity_required'])
            })

    # 2. Iterate and Calculate Metrics (MRP Logic)
    for p in products_list:
        lead_time = p.lead_time_days
        lt_end_date = today + timedelta(days=lead_time)
        current_soh = float(p.qty_on_hand or 0)
        daily_usage = float(p.estimated_daily_usage or 0)

        p.lt_arrival_date = lt_end_date
        p.calc_safety_target_qty = daily_usage * p.safety_stock_days

        demands = demand_map.get(p.id, [])
        demands.sort(key=lambda x: x['date'])

        # Calculate LT Usage & Projected Stock
        usage_in_lt = sum(d['qty'] for d in demands if d['date'] <= lt_end_date)
        p.calc_usage_in_lt = usage_in_lt
        p.calc_projected_safety = current_soh - usage_in_lt

        # Days of Cover at Arrival
        if daily_usage > 0:
            p.calc_cover_at_lt_days = p.calc_projected_safety / daily_usage
        else:
            p.calc_cover_at_lt_days = 999 if p.calc_projected_safety > 0 else 0

        # Run-out Date Logic
        runout_date = None
        temp_balance = current_soh
        for d in demands:
            temp_balance -= d['qty']
            if temp_balance < 0:
                runout_date = d['date']
                break

        if runout_date:
            p.days_until_runout = (runout_date - today).days
        else:
            p.days_until_runout = None

        if daily_usage > 0:
            p.stock_coverage_days = current_soh / daily_usage
        else:
            p.stock_coverage_days = 999 if current_soh > 0 else 0

        # Action Plan Status
        p.mrp_status = "OK"
        p.mrp_action_msg = "No Action Needed"
        p.mrp_color = "bg-emerald-50 text-emerald-700 border-emerald-200"

        if runout_date:
            must_order_by = runout_date - timedelta(days=lead_time)
            days_until_order = (must_order_by - today).days
            p.mrp_runout_date = runout_date
            p.mrp_order_deadline = must_order_by

            if days_until_order < 0:
                p.mrp_status = "URGENT"
                p.mrp_action_msg = f"OVERDUE! Order immediately ({abs(days_until_order)} days late)"
                p.mrp_color = "bg-red-100 text-red-800 border-red-300 animate-pulse"
            elif days_until_order == 0:
                p.mrp_status = "NOW"
                p.mrp_action_msg = "Order Today to avoid shortage"
                p.mrp_color = "bg-red-50 text-red-700 border-red-200"
            elif days_until_order <= 7:
                p.mrp_status = "SOON"
                p.mrp_action_msg = f"Order in {days_until_order} days (by {must_order_by.strftime('%d/%m')})"
                p.mrp_color = "bg-orange-50 text-orange-700 border-orange-200"
            else:
                p.mrp_status = "PLAN"
                p.mrp_action_msg = f"Order by {must_order_by.strftime('%d/%m')}"
                p.mrp_color = "bg-blue-50 text-blue-700 border-blue-200"
        else:
            # Fallback based on daily usage / coverage
            daily = float(p.estimated_daily_usage or 0)
            if daily > 0 and temp_balance > 0:
                days_left = temp_balance / daily
                if days_left < lead_time:
                     p.mrp_status = "LOW"
                     p.mrp_action_msg = "Low Stock (Based on Avg Usage)"
                     p.mrp_color = "bg-amber-50 text-amber-700 border-amber-200"
                else:
                     p.mrp_action_msg = f"Safe for {int(days_left)} days"

    # === End Logic ===

    all_categories = Product.objects.filter(nature=nature_code).values_list('category', flat=True).distinct().order_by('category')
    groups = ProductGroup.objects.filter(nature=nature_code)

    # --- Build Tabs Data ---
    tabs_data = []

    # 1. All Tab
    tabs_data.append({
        'group_id': 'ALL',
        'name': f'All {nature_code}',
        'is_all': True,
        'assets': products_list
    })

    # 2. Group Tabs
    for group in groups:
        group_assets = [p for p in products_list if p.group_id == group.id]
        tabs_data.append({
            'group_id': group.id,
            'name': group.name,
            'is_all': False,
            'assets': group_assets
        })

    titles = {'RAW': 'Raw Materials', 'PKG': 'Packaging', 'FG': 'Finished Goods'}
    context = {
        'page_title': titles.get(nature_code, 'Inventory'),
        'current_nature': nature_code,
        'tabs_data': tabs_data,
        'groups_available': groups,
        'all_categories': all_categories,
        'current_search': search_query,
        'current_category': category_filter,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
         return render(request, 'inventory/partials/inventory_content.html', context)

    return render(request, 'inventory/inventory_list.html', context)


@login_required
def product_demand_analysis(request, pk):
    """
    Returns detailed demand analysis for a specific product:
    1. Orders consuming stock during Lead Time.
    2. Orders that will exhaust the current balance (Run-out analysis), EXCLUDING those already in LT.
    """
    product = get_object_or_404(Product, pk=pk)

    # 1. Get Current Stock
    last_snapshot = InventorySnapshot.objects.filter(product=product).order_by('-snapshot_date').first()
    current_soh = float(last_snapshot.quantity_on_hand) if last_snapshot else 0.0

    # 2. Get Lead Time Date
    lead_time = product.lead_time_days
    today = timezone.now().date()
    lt_end_date = today + timedelta(days=lead_time)

    # 3. Fetch All Active Demands (Sorted by Date)
    active_components = ProductionComponent.objects.filter(
        component=product,
        production_order__status__in=['DRAFT', 'CONFIRMED', 'IN_PROGRESS']
    ).select_related('production_order', 'production_order__product').order_by('production_order__start_date')

    lt_usage_list = []
    run_out_list = []

    # Unified Logic: Calculate running balance through time
    running_balance = current_soh

    for item in active_components:
        ord_date = item.production_order.start_date
        qty = float(item.quantity_required)

        # Get FG Description
        fg_desc = item.production_order.product.description if item.production_order.product else "Unknown Product"

        if ord_date <= lt_end_date:
            # === Table 1: Usage During Lead Time ===
            # Always list these requirements so user knows what is needed immediately.
            running_balance -= qty

            lt_usage_list.append({
                'order_ref': item.production_order.order_number,
                'order_desc': fg_desc,
                'date': ord_date.strftime('%Y-%m-%d'),
                'qty': qty,
                'status': item.production_order.status,
                'balance_after': running_balance # Display actual balance (can be negative here to show immediate shortage)
            })
        else:
            # === Table 2: Run-out Projection (Post-Lead Time) ===
            # If stock is already exhausted by LT orders, we stop projecting (Table 2 is empty)
            if running_balance <= 0:
                break

            new_balance = running_balance - qty
            is_breaker = (new_balance < 0)

            run_out_list.append({
                'order_ref': item.production_order.order_number,
                'order_desc': fg_desc,
                'date': ord_date.strftime('%Y-%m-%d'),
                'qty': qty,
                'balance_after': max(0, new_balance), # Floor at 0 for visual clarity in projection
                'is_breaker': is_breaker
            })

            running_balance = new_balance

    return JsonResponse({
        'status': 'ok',
        'sku': product.sku,
        'description': product.description,
        'lead_time': lead_time,
        'eta': lt_end_date.strftime('%Y-%m-%d'),
        'current_stock': current_soh,
        'lt_data': lt_usage_list,
        'run_out_data': run_out_list
    })

@login_required
@csrf_exempt
def group_create(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        nature = data.get('nature', 'RAW')
        if name:
            group = ProductGroup.objects.create(name=name, nature=nature)
            return JsonResponse({'status': 'ok', 'group_id': group.id})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def group_rename(request, group_id):
    if request.method == 'POST':
        group = get_object_or_404(ProductGroup, id=group_id)
        data = json.loads(request.body)
        group.name = data.get('name', group.name)
        group.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def group_delete(request, group_id):
    if request.method == 'POST':
        group = get_object_or_404(ProductGroup, id=group_id)
        group.delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def product_move(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        data = json.loads(request.body)
        group_id = data.get('group_id')
        if group_id == 'NONE':
            product.group = None
        else:
            new_group = get_object_or_404(ProductGroup, id=group_id)
            product.group = new_group
        product.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def product_reorder(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        order_list = data.get('order', [])
        for index, prod_id in enumerate(order_list):
            Product.objects.filter(id=prod_id).update(sort_order=index)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'})

@login_required
def load_import_modal(request):
    return render(request, 'inventory/partials/import_modal_step1_upload.html')

@login_required
def process_import_file(request):
    if request.method == "POST" and request.FILES.get('file_upload'):
        try:
            file_obj = request.FILES['file_upload']
            df = extract_data_from_file(file_obj)

            if df is not None and not df.empty:
                df = normalize_columns(df)

            if df is None or df.empty:
                return JsonResponse({'success': False, 'message': 'File is empty or unreadable.'})

            items_to_confirm = []
            all_products_qs = Product.objects.all()
            sku_map = {p.sku.upper(): p for p in all_products_qs if p.sku}
            desc_map = {p.description.lower(): p for p in all_products_qs if p.description}
            alias_map = {a.alias_name.lower(): a.product for a in ProductAlias.objects.select_related('product').all()}
            id_map = {p.id: p for p in all_products_qs}

            records = df.fillna('').to_dict('records')

            for row in records:
                import_sku = str(row.get('sku', '')).strip()
                import_name = str(row.get('name', '')).strip()

                def parse_decimal(val):
                    try: return float(str(val).replace(',', ''))
                    except: return 0.0

                qty = parse_decimal(row.get('quantity', 0))
                weight = parse_decimal(row.get('weight', 0))
                volume = parse_decimal(row.get('volume', 0))
                price = parse_decimal(row.get('cost', 0))

                moq = parse_decimal(row.get('moq', 0))
                lead_time = int(parse_decimal(row.get('lead_time', 0)))
                daily_usage = parse_decimal(row.get('daily_usage', 0))

                raw_nature = str(row.get('nature', 'RAW')).strip().upper()
                if raw_nature in ['INGREDIENT', 'RAW MATERIAL', 'RAW']:
                    nature = 'RAW'
                elif raw_nature in ['PACKAGING', 'CONTAINER', 'LABEL', 'PKG', 'CLOSURE', 'CARTON']:
                    nature = 'PKG'
                elif raw_nature in ['FINISHED GOOD', 'FG', 'PRODUCT', 'SYRUPS', 'SAUCES', 'PUREE']:
                    nature = 'FG'
                else:
                    nature = raw_nature if raw_nature in ['RAW', 'PKG', 'FG'] else 'RAW'

                category = row.get('category') or 'General'
                supplier = str(row.get('supplier', '')).strip()

                suggested_product_id = None
                match_score = 0
                match_type = 'NEW'

                if import_sku and import_sku.upper() in sku_map:
                    product = sku_map[import_sku.upper()]
                    suggested_product_id = product.id
                    is_desc_match = (product.description.lower() == import_name.lower())
                    if not is_desc_match:
                        if import_name.lower() in alias_map and alias_map[import_name.lower()].id == product.id:
                            is_desc_match = True
                    if is_desc_match:
                        match_score = 100
                        match_type = 'EXACT'
                    else:
                        match_score = 90
                        match_type = 'SKU_ONLY'

                elif import_name:
                    import_name_lower = import_name.lower()
                    if import_name_lower in desc_map:
                        product = desc_map[import_name_lower]
                        suggested_product_id = product.id
                        match_score = 100
                        match_type = 'NAME_EXACT'
                    elif import_name_lower in alias_map:
                        product = alias_map[import_name_lower]
                        suggested_product_id = product.id
                        match_score = 100
                        match_type = 'ALIAS_MATCH'
                    else:
                        choices = list(desc_map.keys())
                        if choices:
                            match = process.extractOne(import_name_lower, choices, scorer=fuzz.WRatio)
                            if match and match[1] >= 60:
                                best_match_desc = match[0]
                                product = desc_map[best_match_desc]
                                suggested_product_id = product.id
                                match_score = int(match[1])
                                match_type = 'FUZZY'

                is_weight_mismatch = False
                system_weight = 0

                if suggested_product_id and suggested_product_id in id_map:
                    matched_product = id_map[suggested_product_id]
                    system_weight = matched_product.unit_weight
                    try:
                        import_weight_dec = Decimal(str(weight))
                        if system_weight > 0 and import_weight_dec > 0:
                            if abs(system_weight - import_weight_dec) > Decimal('0.01'):
                                is_weight_mismatch = True
                    except:
                        pass

                items_to_confirm.append({
                    'import_sku': import_sku,
                    'import_name': import_name,
                    'import_qty': qty,
                    'import_weight': weight,
                    'import_volume': volume,
                    'import_price': price,
                    'import_supplier': supplier,
                    'import_nature': nature,
                    'import_category': category,
                    'import_moq': moq,
                    'import_lead_time': lead_time,
                    'import_daily_usage': daily_usage,
                    'suggested_product_id': suggested_product_id,
                    'match_score': match_score,
                    'match_type': match_type,
                    'is_weight_mismatch': is_weight_mismatch,
                    'system_weight': float(system_weight),
                })

            items_to_confirm.sort(key=lambda x: (
                0 if x.get('is_weight_mismatch') else 1,
                x.get('match_score', 0) * -1
            ))

            request.session['temp_import_data'] = items_to_confirm
            html = render_to_string('inventory/partials/import_modal_step2_preview.html', {
                'items_to_confirm': items_to_confirm,
                'all_products': all_products_qs.order_by('sku')
            }, request=request)

            return JsonResponse({'success': True, 'html': html})

        except Exception as e:
            return JsonResponse({'success': False, 'message': f"Process Error: {str(e)}"})

    return JsonResponse({'success': False, 'message': 'Invalid Request'})


@login_required
@csrf_exempt
def product_delete(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        product.delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def finalize_import(request):
    if request.method == "POST":
        import_data = request.session.get('temp_import_data')
        if not import_data:
            return JsonResponse({'success': False, 'message': 'Session expired.'})

        try:
            with transaction.atomic():
                snapshot_date = timezone.now().date()
                stats = {'created': 0, 'updated_alias': 0, 'updated_supplier': 0, 'temp_created': 0, 'skipped': 0}

                for i, item in enumerate(import_data):
                    selection = request.POST.get(f'product_selection_{i}')
                    def to_dec(val):
                        try: return Decimal(str(val))
                        except: return Decimal('0')

                    weight_val = to_dec(item.get('import_weight', 0))
                    qty_val = to_dec(item.get('import_qty', 0))
                    price_val = to_dec(item.get('import_price', 0))
                    volume_val = to_dec(item.get('import_volume', 0))
                    moq_val = to_dec(item.get('import_moq', 0))
                    lead_time_val = int(item.get('import_lead_time', 0))
                    daily_usage_val = to_dec(item.get('import_daily_usage', 0))

                    import_desc = item.get('import_name', '').strip()
                    supplier_val_str = item.get('import_supplier', '').strip()

                    supplier_obj = None
                    if supplier_val_str:
                        supplier_obj, _ = Supplier.objects.get_or_create(name=supplier_val_str)

                    if not selection or selection == 'SKIP':
                        stats['skipped'] += 1
                        continue

                    elif selection == 'CREATE':
                        provided_sku = item.get('import_sku', '').strip()
                        if provided_sku:
                            new_sku = provided_sku[:50]
                        else:
                            base = slugify(import_desc)[:20].upper() or "NEW"
                            new_sku = f"{base}-{random.randint(1000,9999)}"

                        product = Product.objects.create(
                            sku=new_sku,
                            description=import_desc,
                            nature=item.get('import_nature', 'RAW'),
                            category=item.get('import_category', 'None'),
                            unit_weight=weight_val,
                            unit_volume=volume_val,
                            cost_price=price_val,
                            supplier=supplier_obj,
                            is_temporary=False,
                            moq=moq_val,
                            lead_time_days=lead_time_val,
                            estimated_daily_usage=daily_usage_val
                        )

                        if qty_val > 0:
                            InventorySnapshot.objects.update_or_create(
                                product=product, snapshot_date=snapshot_date,
                                defaults={'quantity_on_hand': qty_val}
                            )
                        stats['created'] += 1

                    else:
                        # === MATCH FOUND: CREATE TEMPORARY PRODUCT ONLY IF DIFF ===
                        try:
                            target_product_id = selection
                            original_product = Product.objects.get(id=target_product_id)

                            # 1. Fetch Current Stock
                            latest_snapshot = InventorySnapshot.objects.filter(product=original_product).order_by('-snapshot_date').first()
                            current_qty = latest_snapshot.quantity_on_hand if latest_snapshot else Decimal('0')

                            # 2. Check for Differences
                            has_diff = False

                            def is_diff(v1, v2):
                                return abs(v1 - (v2 or Decimal('0'))) > Decimal('0.01')

                            # Stock Diff
                            if is_diff(qty_val, current_qty): has_diff = True

                            # Master Data Diff (Weight, Cost, LeadTime, MOQ, Usage)
                            if is_diff(weight_val, original_product.unit_weight): has_diff = True
                            if is_diff(price_val, original_product.cost_price): has_diff = True
                            if is_diff(moq_val, original_product.moq): has_diff = True
                            if is_diff(daily_usage_val, original_product.estimated_daily_usage): has_diff = True
                            if lead_time_val != original_product.lead_time_days: has_diff = True

                            # Category Diff (Ignore General default)
                            imp_cat = item.get('import_category')
                            sys_cat = original_product.category or ""
                            if imp_cat and imp_cat != 'General' and imp_cat != sys_cat:
                                has_diff = True

                            # Supplier Diff
                            imp_supp = supplier_val_str
                            sys_supp = original_product.supplier.name if original_product.supplier else ""
                            if imp_supp and imp_supp != sys_supp:
                                has_diff = True

                            if has_diff:
                                # Create Temp Product (IMP-SKU)
                                provided_sku = item.get('import_sku', '').strip()
                                base_sku = provided_sku if provided_sku else original_product.sku
                                temp_sku = f"IMP-{base_sku}-{random.randint(1000,9999)}"[:50]
                                final_desc = f"{import_desc} [Review]" if import_desc else f"{original_product.description} [Review]"

                                temp_product = Product.objects.create(
                                    sku=temp_sku,
                                    description=final_desc,
                                    nature=item.get('import_nature', original_product.nature),
                                    category=item.get('import_category', original_product.category),
                                    unit_weight=weight_val,
                                    unit_volume=volume_val,
                                    cost_price=price_val,
                                    supplier=supplier_obj,
                                    is_temporary=True,
                                    moq=moq_val,
                                    lead_time_days=lead_time_val,
                                    estimated_daily_usage=daily_usage_val
                                )

                                if qty_val > 0:
                                    InventorySnapshot.objects.create(
                                        product=temp_product,
                                        snapshot_date=snapshot_date,
                                        quantity_on_hand=qty_val
                                    )
                                stats['temp_created'] += 1
                            else:
                                stats['skipped'] += 1
                                # Optional: Update Aliases even if skipped
                                if import_desc and import_desc != original_product.description:
                                     exists = ProductAlias.objects.filter(product=original_product, alias_name=import_desc).exists()
                                     if not exists:
                                        ProductAlias.objects.create(product=original_product, alias_name=import_desc)
                                        stats['updated_alias'] += 1

                        except Product.DoesNotExist:
                            continue

            del request.session['temp_import_data']
            msg = (f"Import Result: {stats['created']} Created, "
                   f"{stats['temp_created']} Temps (Changes Detected), "
                   f"{stats['skipped']} Skipped (No Change).")
            return JsonResponse({'success': True, 'message': msg})

        except Exception as e:
            return JsonResponse({'success': False, 'message': f"Error: {str(e)}"})

    return JsonResponse({'success': False, 'message': 'POST required'})

@login_required
@csrf_exempt
def product_update(request, pk):
    if request.method == 'POST':
        try:
            product = get_object_or_404(Product, pk=pk)
            data = json.loads(request.body)
            if product.is_temporary:
                new_sku = data.get('sku', '').strip()
                if new_sku and new_sku != product.sku:
                    if Product.objects.filter(sku=new_sku).exclude(pk=pk).exists():
                         return JsonResponse({'status': 'error', 'message': 'SKU already exists'}, status=400)
                    product.sku = new_sku
                    if not new_sku.upper().startswith('TEMP-') and not new_sku.upper().startswith('IMP-'):
                        product.is_temporary = False

            product.description = data.get('description', product.description)
            product.category = data.get('category', product.category)
            product.uom = data.get('uom', product.uom)
            product.unit_weight = data.get('unit_weight', product.unit_weight)
            product.unit_volume = data.get('unit_volume', product.unit_volume)
            product.safety_stock_days = data.get('safety_stock_days', product.safety_stock_days)
            product.lead_time_days = data.get('lead_time_days', product.lead_time_days)
            product.estimated_daily_usage = data.get('estimated_daily_usage', product.estimated_daily_usage)
            product.moq = data.get('moq', product.moq)

            product.save()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=405)

@login_required
@csrf_exempt
def category_rename(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            old_name = data.get('old_name')
            new_name = data.get('new_name')
            nature = data.get('nature')
            if not old_name or not new_name:
                 return JsonResponse({'status': 'error', 'message': 'Missing parameters'}, status=400)
            qs = Product.objects.filter(category=old_name)
            if nature:
                qs = qs.filter(nature=nature)
            updated_count = qs.update(category=new_name)
            return JsonResponse({'status': 'ok', 'updated': updated_count})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def category_delete(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            category_name = data.get('category_name')
            nature = data.get('nature')
            if not category_name:
                return JsonResponse({'status': 'error', 'message': 'Missing category name'}, status=400)
            qs = Product.objects.filter(category=category_name)
            if nature:
                qs = qs.filter(nature=nature)
            updated_count = qs.update(category='General')
            return JsonResponse({'status': 'ok', 'updated': updated_count})
        except Exception as e:
             return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def bom_list(request, product_id):
    try:
        boms = BillOfMaterial.objects.filter(product_id=product_id).select_related('component').order_by('component__sku')
        data = []
        for bom in boms:
            data.append({
                'id': bom.id,
                'component_id': bom.component.id,
                'component_sku': bom.component.sku,
                'component_name': bom.component.description,
                'component_uom': bom.component.uom,
                'quantity': float(bom.quantity)
            })
        return JsonResponse({'status': 'ok', 'data': data})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@csrf_exempt
def bom_add(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = data.get('product_id')
            component_id = data.get('component_id')
            raw_qty = data.get('quantity', 1)
            try:
                if not raw_qty: quantity = Decimal('1')
                else: quantity = Decimal(str(raw_qty))
            except Exception:
                quantity = Decimal('1')

            product = get_object_or_404(Product, id=product_id)
            component = get_object_or_404(Product, id=component_id)

            bom, created = BillOfMaterial.objects.get_or_create(
                product=product,
                component=component,
                defaults={'quantity': quantity}
            )
            if not created:
                bom.quantity = quantity
                bom.save()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def bom_update(request, bom_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            quantity = data.get('quantity')
            bom = get_object_or_404(BillOfMaterial, id=bom_id)
            bom.quantity = Decimal(str(quantity))
            bom.save()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@login_required
@csrf_exempt
def bom_delete(request, bom_id):
    if request.method == 'POST':
        try:
            bom = get_object_or_404(BillOfMaterial, id=bom_id)
            bom.delete()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def product_search_components(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})
    products = Product.objects.filter(
        Q(sku__icontains=query) | Q(description__icontains=query)
    ).exclude(nature='FG')[:10]
    results = [{
        'id': p.id,
        'sku': p.sku,
        'name': p.description,
        'uom': p.uom,
        'unit_weight': float(p.unit_weight),
        'unit_volume': float(p.unit_volume)
    } for p in products]
    return JsonResponse({'results': results})

@login_required
def load_bom_import_modal(request):
    """Step 1: Render the file upload form for BOMs."""
    return render(request, 'inventory/partials/import_bom_modal_step1.html')

@login_required
def process_bom_import_file(request):
    """Step 2: Read file, match Products, and show preview."""
    if request.method == "POST" and request.FILES.get('file_upload'):
        try:
            file_obj = request.FILES['file_upload']
            df = extract_data_from_file(file_obj) # Reusing your existing service

            if df is None or df.empty:
                return JsonResponse({'success': False, 'message': 'File is empty.'})

            # Normalize headers specifically for BOM
            # We look for: Parent (FG), Component (Raw), Quantity
            df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

            # Map columns
            col_parent = next((c for c in df.columns if c in ['parent_sku', 'fg_sku', 'finished_good', 'parent']), None)
            col_comp = next((c for c in df.columns if c in ['component_sku', 'child_sku', 'raw_material', 'component']), None)
            col_qty = next((c for c in df.columns if c in ['quantity', 'qty', 'amount', 'usage']), None)

            if not (col_parent and col_comp and col_qty):
                 return JsonResponse({'success': False, 'message': 'Missing columns. Required: "Parent SKU", "Component SKU", "Quantity"'})

            # Prepare Lookups
            all_products = Product.objects.all()
            sku_map = {p.sku.upper(): p for p in all_products}

            preview_data = []

            for _, row in df.iterrows():
                p_val = str(row[col_parent]).strip()
                c_val = str(row[col_comp]).strip()
                q_val = row[col_qty]

                try:
                    qty = float(q_val)
                except:
                    qty = 0

                # Match Parent (Must be FG)
                parent_obj = sku_map.get(p_val.upper())
                parent_status = 'OK'
                if not parent_obj:
                    parent_status = 'NOT_FOUND'
                elif parent_obj.nature != 'FG':
                    parent_status = 'NOT_FG' # Warning: Parent should ideally be FG

                # Match Component
                comp_obj = sku_map.get(c_val.upper())
                comp_status = 'OK'
                if not comp_obj:
                    comp_status = 'NOT_FOUND'
                elif comp_obj.id == (parent_obj.id if parent_obj else -1):
                    comp_status = 'SELF_REF' # Cannot start loop

                preview_data.append({
                    'parent_input': p_val,
                    'parent_found': parent_obj.sku if parent_obj else None,
                    'parent_id': parent_obj.id if parent_obj else None,
                    'parent_status': parent_status,

                    'comp_input': c_val,
                    'comp_found': comp_obj.sku if comp_obj else None,
                    'comp_id': comp_obj.id if comp_obj else None,
                    'comp_status': comp_status,

                    'qty': qty
                })

            # Sort: Errors first
            preview_data.sort(key=lambda x: 0 if (x['parent_status'] == 'OK' and x['comp_status'] == 'OK') else 1, reverse=True)

            request.session['temp_bom_import'] = preview_data

            html = render_to_string('inventory/partials/import_bom_modal_step2.html', {
                'items': preview_data
            }, request=request)

            return JsonResponse({'success': True, 'html': html})

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
@csrf_exempt
def finalize_bom_import(request):
    """Step 3: Save valid BOM connections."""
    if request.method == 'POST':
        data = request.session.get('temp_bom_import')
        if not data:
            return JsonResponse({'success': False, 'message': 'Session expired'})

        created_count = 0
        updated_count = 0
        errors = 0

        try:
            with transaction.atomic():
                for item in data:
                    # Skip invalid rows
                    if not (item['parent_id'] and item['comp_id']):
                        continue

                    # Logic: Create or Update BOM
                    # User selection check could be added here if we had checkboxes in UI

                    parent = Product.objects.get(id=item['parent_id'])
                    component = Product.objects.get(id=item['comp_id'])
                    qty = Decimal(str(item['qty']))

                    obj, created = BillOfMaterial.objects.update_or_create(
                        product=parent,
                        component=component,
                        defaults={'quantity': qty}
                    )

                    if created:
                        created_count += 1
                    else:
                        updated_count += 1

            del request.session['temp_bom_import']
            return JsonResponse({
                'success': True,
                'message': f"Success! Created {created_count} new recipes, Updated {updated_count} existing."
            })

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})

    return JsonResponse({'success': False, 'message': 'Post required'})
