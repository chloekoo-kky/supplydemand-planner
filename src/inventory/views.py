import random
import json

from django.db.models import Case, When, Sum, F, Subquery, OuterRef, Q, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from rapidfuzz import process, fuzz
from decimal import Decimal


from .models import (
    Product, ProductGroup, InventorySnapshot,
    ProductAlias, Supplier, BillOfMaterial
)
from production.models import ProductionOrder, ProductionComponent
from .services import extract_data_from_file


def inventory_list(request, nature_code=None):
    nature_code = nature_code.upper() if nature_code else 'RAW'

    # 定义状态分类
    STATUS_HARD_WIP = ['CONFIRMED', 'IN_PROGRESS'] # 硬承诺 (WIP)
    STATUS_SOFT_DRAFT = ['DRAFT']                  # 软承诺 (Budget)

    # --- 1. 准备 Subqueries (避免 N+1 查询) ---

    # A. 基础库存快照
    latest_stock = InventorySnapshot.objects.filter(
        product=OuterRef('pk')
    ).order_by('-snapshot_date')

    # B. FG (成品) 的 WIP (Inbound)
    # 逻辑：查找该产品作为 FG 的工单，且状态是 CONFIRMED/IN_PROGRESS
    fg_wip_qs = ProductionOrder.objects.filter(
        product=OuterRef('pk'),
        status__in=STATUS_HARD_WIP
    ).values('product').annotate(total=Sum('quantity')).values('total')

    # C. FG (成品) 的 Draft (Potential Inbound)
    fg_draft_qs = ProductionOrder.objects.filter(
        product=OuterRef('pk'),
        status__in=STATUS_SOFT_DRAFT
    ).values('product').annotate(total=Sum('quantity')).values('total')

    # D. RM (原料) 的 Draft Usage (Soft Allocation)
    # 逻辑：查找该原料被哪些 'DRAFT' 状态的工单引用了 (通过 ProductionComponent)
    # 注意：这要求 Draft 工单在创建时就生成了 ProductionComponent 记录
    rm_draft_qs = ProductionComponent.objects.filter(
        component=OuterRef('pk'),
        production_order__status__in=STATUS_SOFT_DRAFT
    ).values('component').annotate(total=Sum('quantity_required')).values('total')

    # --- 2. 主查询 ---
    all_products_qs = Product.objects.filter(nature=nature_code).select_related('supplier').annotate(
        # 1. On Hand (OH) - 物理库存
        qty_on_hand=Coalesce(Subquery(latest_stock.values('quantity_on_hand')[:1]), Value(0, output_field=DecimalField())),

        # 2. Reserved (Hard WIP) - 硬预留
        # 对于 RM，这部分通常在 Production Service 里更新到了 InventorySnapshot.quantity_reserved
        qty_reserved=Coalesce(Subquery(latest_stock.values('quantity_reserved')[:1]), Value(0, output_field=DecimalField())),

        # 3. FG Inbound (FG Only)
        qty_fg_wip=Coalesce(Subquery(fg_wip_qs[:1]), Value(0, output_field=DecimalField())),
        qty_fg_draft=Coalesce(Subquery(fg_draft_qs[:1]), Value(0, output_field=DecimalField())),

        # 4. RM Draft Alloc (RM Only)
        qty_rm_draft=Coalesce(Subquery(rm_draft_qs[:1]), Value(0, output_field=DecimalField())),
    ).annotate(
        # --- 3. 计算 Net Available (公式) ---
        # 逻辑：
        # 如果是 Raw/Pkg: Net = OH - Reserved (硬预留)
        # 如果是 FG:      Net = OH + WIP (在途产出) -> 可供销售
        net_available=Case(
            When(nature='FG', then=F('qty_on_hand') + F('qty_fg_wip')),
            default=F('qty_on_hand') - F('qty_reserved'), # RAW/PKG
            output_field=DecimalField()
        ),

        # --- 4. 计算 Projected (包含 Draft) ---
        # 逻辑：
        # 如果是 Raw/Pkg: Proj = Net - Draft_Usage
        # 如果是 FG:      Proj = Net + Draft_Production
        projected_stock=Case(
            When(nature='FG', then=F('net_available') + F('qty_fg_draft')),
            default=F('net_available') - F('qty_rm_draft'),
            output_field=DecimalField()
        )
    ).order_by('-is_temporary', 'sort_order', 'sku')

    # --- 搜索 & 筛选逻辑 (保持不变) ---
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

    all_categories = Product.objects.filter(nature=nature_code).values_list('category', flat=True).distinct().order_by('category')
    groups = ProductGroup.objects.filter(nature=nature_code)

    # --- 构建 Tabs 数据 ---
    tabs_data = []
    tabs_data.append({
        'group_id': 'ALL',
        'name': f'All {nature_code}',
        'is_all': True,
        'assets': all_products_qs
    })

    for group in groups:
        group_assets = all_products_qs.filter(group=group)
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


@csrf_exempt
def group_create(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        nature = data.get('nature', 'RAW')
        if name:
            group = ProductGroup.objects.create(name=name, nature=nature)
            # 【关键修改】返回新创建的 group.id
            return JsonResponse({'status': 'ok', 'group_id': group.id})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
def group_rename(request, group_id):
    if request.method == 'POST':
        group = get_object_or_404(ProductGroup, id=group_id)
        data = json.loads(request.body)
        group.name = data.get('name', group.name)
        group.save()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
def group_delete(request, group_id):
    if request.method == 'POST':
        group = get_object_or_404(ProductGroup, id=group_id)
        # 删除组后，产品自动变回 "未分组" (group=None)，依然会在 "All Items" 中显示
        group.delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
def product_move(request, product_id):
    """将产品移动到另一个 Group"""
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

@csrf_exempt
def product_reorder(request):
    """处理卡片拖拽排序"""
    if request.method == 'POST':
        data = json.loads(request.body)
        order_list = data.get('order', [])
        for index, prod_id in enumerate(order_list):
            # 这里的更新比较粗暴，适合数据量不大的情况
            Product.objects.filter(id=prod_id).update(sort_order=index)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'})

def load_import_modal(request):
    return render(request, 'inventory/partials/import_modal_step1_upload.html')

# 2. 处理上传并显示预览 (Modal 第二步)
def process_import_file(request):
    """
    视图函数：处理文件上传，解析数据，并与数据库进行智能比对
    """
    if request.method == "POST" and request.FILES.get('file_upload'):
        try:
            file_obj = request.FILES['file_upload']
            df = extract_data_from_file(file_obj)

            if df is None or df.empty:
                return JsonResponse({'success': False, 'message': '文件为空或无法读取表格数据'})

            items_to_confirm = []

            # 预加载所有产品数据
            all_products_qs = Product.objects.all()

            # 构建查找字典
            sku_map = {p.sku.upper(): p for p in all_products_qs if p.sku}
            desc_map = {p.description.lower(): p for p in all_products_qs if p.description}
            alias_map = {a.alias_name.lower(): a.product for a in ProductAlias.objects.select_related('product').all()}
            # 辅助字典：通过 ID 快速获取产品对象，用于后续比对重量
            id_map = {p.id: p for p in all_products_qs}

            records = df.fillna('').to_dict('records')

            for row in records:
                # --- A. 提取并清洗基础数据 ---
                import_sku = str(row.get('import_sku', '')).strip()
                import_name = str(row.get('import_description', '')).strip()

                try: qty = float(row.get('import_qty', 0))
                except: qty = 0

                # 重量处理：保留 float 用于前端显示，但在比较时转 Decimal
                try: weight = float(row.get('import_weight', 0))
                except: weight = 0

                try: volume = float(row.get('import_volume', 0))
                except: volume = 0
                try: price = float(row.get('import_price', 0))
                except: price = 0

                nature = row.get('import_nature', 'RAW')
                category = row.get('import_category', 'None')
                supplier = str(row.get('import_supplier', '')).strip()

                # --- B. 智能匹配逻辑 ---
                suggested_product_id = None
                match_score = 0
                match_type = 'NEW'

                # 1. SKU 匹配
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

                # 2. Description / Alias 匹配
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

                # --- C. 冲突检测 (新增逻辑) ---
                is_weight_mismatch = False
                system_weight = 0

                if suggested_product_id and suggested_product_id in id_map:
                    matched_product = id_map[suggested_product_id]
                    system_weight = matched_product.unit_weight # Decimal 类型

                    # 将导入重量转为 Decimal 进行安全比较
                    try:
                        import_weight_dec = Decimal(str(weight))
                        # 只有当两者都 > 0 且差值超过 0.01 时才算冲突
                        if system_weight > 0 and import_weight_dec > 0:
                            if abs(system_weight - import_weight_dec) > Decimal('0.01'):
                                is_weight_mismatch = True
                    except:
                        pass # 转换失败就不比了

                items_to_confirm.append({
                    'import_sku': import_sku,
                    'import_name': import_name,
                    'import_qty': qty,
                    'import_weight': weight, # float
                    'import_volume': volume,
                    'import_price': price,
                    'import_supplier': supplier,
                    'import_nature': nature,
                    'import_category': category,

                    'suggested_product_id': suggested_product_id,
                    'match_score': match_score,
                    'match_type': match_type,

                    # 新增字段传给前端
                    'is_weight_mismatch': is_weight_mismatch,
                    'system_weight': float(system_weight),
                })

            # --- D. 排序逻辑 (修改) ---
            NATURE_ORDER = {'RAW': 0, 'PKG': 1, 'FG': 2}

            items_to_confirm.sort(key=lambda x: (
                # 优先级 0: 有冲突的排在最前面 (False=0, True=1, 所以用 not x 也就是 True(1) 排后? 不对，True要排前)
                # 我们希望 True 排在 False 前面。 sort 默认是升序。
                # 0 排在 1 前面。所以让 True = 0, False = 1
                0 if x.get('is_weight_mismatch') else 1,

                NATURE_ORDER.get(x.get('import_nature', 'RAW'), 99),
                x.get('import_name', '').lower()
            ))

            request.session['temp_import_data'] = items_to_confirm

            html = render_to_string('inventory/partials/import_modal_step2_preview.html', {
                'items_to_confirm': items_to_confirm,
                'all_products': all_products_qs.order_by('sku')
            }, request=request)

            return JsonResponse({'success': True, 'html': html})

        except Exception as e:
            print(f"Import Error: {e}")
            return JsonResponse({'success': False, 'message': f"处理失败: {str(e)}"})

    return JsonResponse({'success': False, 'message': '无效的请求'})

@csrf_exempt
def product_delete(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        product.delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

# 3. 最终确认并保存 (Modal 结束)
@csrf_exempt
def finalize_import(request):
    if request.method == "POST":
        import_data = request.session.get('temp_import_data')
        if not import_data:
            return JsonResponse({'success': False, 'message': 'Session expired.'})

        try:
            with transaction.atomic():
                snapshot_date = timezone.now().date()
                stats = {
                    'created': 0,
                    'updated_alias': 0,
                    'updated_supplier': 0,
                    'temp_created': 0,
                    'skipped': 0
                }

                for i, item in enumerate(import_data):
                    selection = request.POST.get(f'product_selection_{i}')

                    # === 1. 数据解析 (转为 Decimal 以匹配数据库字段类型) ===
                    try:
                        # 先转字符串再转Decimal，避免浮点数精度丢失
                        weight_val = Decimal(str(item.get('import_weight', 0)))
                    except:
                        weight_val = Decimal('0')

                    try:
                        qty_val = Decimal(str(item.get('import_qty', 0)))
                    except:
                        qty_val = Decimal('0')

                    try:
                        price_val = Decimal(str(item.get('import_price', 0)))
                    except:
                        price_val = Decimal('0')

                    try:
                        volume_val = Decimal(str(item.get('import_volume', 0)))
                    except:
                        volume_val = Decimal('0')

                    import_desc = item.get('import_name', '').strip()
                    supplier_val_str = item.get('import_supplier', '').strip()

                    # 准备供应商对象
                    supplier_obj = None
                    if supplier_val_str:
                        supplier_obj, _ = Supplier.objects.get_or_create(name=supplier_val_str)

                    # === 2. 逻辑分支 ===

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
                            is_temporary=False
                        )

                        if qty_val > 0:
                            InventorySnapshot.objects.update_or_create(
                                product=product, snapshot_date=snapshot_date,
                                defaults={'quantity_on_hand': qty_val}
                            )
                        stats['created'] += 1

                    else:
                        try:
                            target_product_id = selection
                            product = Product.objects.get(id=target_product_id)

                            # [冲突检测] 使用 Decimal 进行比较
                            # abs(Decimal - Decimal) > Decimal
                            weight_conflict = (weight_val > 0) and (abs(product.unit_weight - weight_val) > Decimal('0.01'))
                            price_conflict = (price_val > 0) and (abs(product.cost_price - price_val) > Decimal('0.01'))

                            # === 分支 C-1: 有冲突 -> 创建 TEMP 产品 ===
                            if weight_conflict or price_conflict:
                                reasons = []
                                if weight_conflict: reasons.append(f"W:{weight_val}kg")
                                if price_conflict: reasons.append(f"${price_val}")
                                reason_str = " | ".join(reasons)

                                temp_sku = f"TEMP-{product.sku}-{random.randint(100,999)}"

                                temp_product = Product.objects.create(
                                    sku=temp_sku,
                                    description=f"{import_desc} [Check: {reason_str}]",
                                    nature=product.nature,
                                    unit_weight=weight_val,
                                    unit_volume=volume_val,
                                    cost_price=price_val,
                                    supplier=supplier_obj,
                                    is_temporary=True
                                )

                                if qty_val > 0:
                                    InventorySnapshot.objects.create(
                                        product=temp_product,
                                        snapshot_date=snapshot_date,
                                        quantity_on_hand=qty_val
                                    )
                                stats['temp_created'] += 1

                            # === 分支 C-2: 无冲突 -> 完美匹配 ===
                            else:
                                if import_desc and import_desc != product.description:
                                    exists = ProductAlias.objects.filter(product=product, alias_name=import_desc).exists()
                                    if not exists:
                                        ProductAlias.objects.create(product=product, alias_name=import_desc)
                                        stats['updated_alias'] += 1

                                if supplier_obj and product.supplier != supplier_obj:
                                    product.supplier = supplier_obj
                                    product.save(update_fields=['supplier'])
                                    stats['updated_supplier'] += 1

                                pass

                        except Product.DoesNotExist:
                            continue

            del request.session['temp_import_data']

            msg = (f"Import Result: {stats['created']} Created, "
                   f"{stats['temp_created']} Temps (mismatch), "
                   f"{stats['updated_alias']} Aliases learned.")

            return JsonResponse({'success': True, 'message': msg})

        except Exception as e:
            print(f"Finalize Error: {e}")
            return JsonResponse({'success': False, 'message': f"Error: {str(e)}"})

    return JsonResponse({'success': False, 'message': 'POST required'})


@csrf_exempt
def product_update(request, pk):
    """
    处理产品编辑 Modal 的提交
    """
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
                    # If prefix is removed, demote from temporary status
                    if not new_sku.upper().startswith('TEMP-'):
                        product.is_temporary = False

            product.description = data.get('description', product.description)
            product.category = data.get('category', product.category)
            product.uom = data.get('uom', product.uom)
            product.unit_weight = data.get('unit_weight', product.unit_weight)
            product.unit_volume = data.get('unit_volume', product.unit_volume)
            product.safety_stock_days = data.get('safety_stock_days', product.safety_stock_days)
            product.lead_time_days = data.get('lead_time_days', product.lead_time_days)

            product.save()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

@csrf_exempt
def category_rename(request):
    """
    Rename a category: Updates the 'category' field for all products
    matching the old name within the current nature.
    """
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


@csrf_exempt
def category_delete(request):
    """
    Delete a category: Reassigns all products in this category to 'General'.
    """
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

            # Reassign to default
            updated_count = qs.update(category='General')

            return JsonResponse({'status': 'ok', 'updated': updated_count})
        except Exception as e:
             return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

# --- BOM API Views ---

def bom_list(request, product_id):
    """List all components for a Finished Good"""
    try:
        # Use select_related to fetch component details efficiently
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

@csrf_exempt
def bom_add(request):
    """Add a component to a recipe"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = data.get('product_id')
            component_id = data.get('component_id')

            # --- 修复开始: 健壮的数量处理 ---
            raw_qty = data.get('quantity', 1)
            try:
                # 如果为空或无效，默认为 1
                if not raw_qty:
                    quantity = Decimal('1')
                else:
                    quantity = Decimal(str(raw_qty))
            except Exception:
                quantity = Decimal('1')
            # --- 修复结束 ---

            product = get_object_or_404(Product, id=product_id)
            component = get_object_or_404(Product, id=component_id)

            # Check duplication
            # 注意: defaults 里的 quantity 必须是有效的数字/Decimal
            bom, created = BillOfMaterial.objects.get_or_create(
                product=product,
                component=component,
                defaults={'quantity': quantity}
            )

            if not created:
                # If exists, update quantity
                bom.quantity = quantity
                bom.save()

            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
def bom_update(request, bom_id):
    """Update quantity of a BOM line"""
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

@csrf_exempt
def bom_delete(request, bom_id):
    """Remove a component from a recipe"""
    if request.method == 'POST':
        try:
            bom = get_object_or_404(BillOfMaterial, id=bom_id)
            bom.delete()
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=400)

def product_search_components(request):
    """Search for products that are NOT Finished Goods (RAW or PKG)"""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})

    products = Product.objects.filter(
        Q(sku__icontains=query) | Q(description__icontains=query)
    ).exclude(nature='FG')[:10]

    # ⬇️ 修改这里：添加 unit_weight 和 unit_volume 到返回结果中
    results = [{
        'id': p.id,
        'sku': p.sku,
        'name': p.description,
        'uom': p.uom,
        'unit_weight': float(p.unit_weight), # 确保是数字
        'unit_volume': float(p.unit_volume)  # 确保是数字
    } for p in products]

    return JsonResponse({'results': results})
