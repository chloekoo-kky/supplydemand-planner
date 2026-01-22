from django.contrib import admin
from .models import (
    Product, InventorySnapshot, RawMaterial,
    PackagingMaterial, FinishedGoods, Supplier,
    ProductGroup, ProductAlias, BillOfMaterial
)



# --- 1. 全局产品视图 ---
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'description', 'nature', 'category', 'safety_stock_days')
    search_fields = ('sku', 'description', 'category')
    list_filter = ('nature', 'category')
    ordering = ('sku',)

    # Enable quick editing of Category and Safety Stock from the list view
    list_editable = ('category', 'safety_stock_days')

    fields = ('sku', 'description', 'nature', 'category', 'group', 'uom', 'safety_stock_days', 'moq', 'lead_time_days', 'supplier', 'unit_weight', 'unit_volume', 'is_temporary')
    autocomplete_fields = ['supplier', 'group']

# --- 2. 原料 (Raw Material) ---
@admin.register(RawMaterial)
class RawMaterialAdmin(admin.ModelAdmin):
    list_display = ('sku', 'description', 'category', 'lead_time_days', 'safety_stock_days', 'current_stock_preview')
    search_fields = ('sku', 'description')
    list_filter = ('category',)
    ordering = ('sku',)
    exclude = ('nature',)

    def current_stock_preview(self, obj):
        latest = obj.snapshots.order_by('-snapshot_date').first()
        return latest.quantity_on_hand if latest else "-"
    current_stock_preview.short_description = "Latest Stock"

# --- 3. 包材 (Packaging Material) ---
@admin.register(PackagingMaterial)
class PackagingMaterialAdmin(admin.ModelAdmin):
    list_display = ('sku', 'description', 'category', 'moq', 'lead_time_days')
    search_fields = ('sku', 'description')
    list_filter = ('category',)
    ordering = ('sku',)
    exclude = ('nature',)


class BillOfMaterialInline(admin.TabularInline):
    model = BillOfMaterial
    fk_name = 'product'  # Link to the Parent Product
    autocomplete_fields = ['component'] # Searchable dropdown for ingredients
    extra = 1 # Number of empty rows to show
    verbose_name = "Recipe Component"
    verbose_name_plural = "Recipe / Bill of Materials"
    
# --- 4. 成品 (Finished Goods) ---
@admin.register(FinishedGoods)
class FinishedGoodsAdmin(admin.ModelAdmin):
    list_display = ('sku', 'description', 'category', 'uom', 'safety_stock_days')
    search_fields = ('sku', 'description')
    list_filter = ('category',)
    ordering = ('sku',)
    exclude = ('nature',)

    # Add the BOM Inline editor here
    inlines = [BillOfMaterialInline]

# --- 5. 库存快照 (Inventory Snapshot) ---
@admin.register(InventorySnapshot)
class InventorySnapshotAdmin(admin.ModelAdmin):
    list_display = ('snapshot_date', 'product', 'get_product_nature', 'quantity_on_hand', 'quantity_on_order')
    list_filter = ('snapshot_date', 'product__nature', 'product__category')
    date_hierarchy = 'snapshot_date'
    autocomplete_fields = ['product']

    @admin.display(description='Type', ordering='product__nature')
    def get_product_nature(self, obj):
        return obj.product.get_nature_display()

# --- 6. 供应商 (Supplier) ---
@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone')
    search_fields = ('name', 'contact_person')

# --- 7. 产品分组 (Tabs) ---
@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'nature', 'order')
    list_filter = ('nature',)
    ordering = ('nature', 'order')
    search_fields = ('name',)

# --- 8. 产品别名 (Aliases) ---
@admin.register(ProductAlias)
class ProductAliasAdmin(admin.ModelAdmin):
    list_display = ('alias_name', 'product')
    search_fields = ('alias_name', 'product__sku', 'product__description')
    autocomplete_fields = ['product']
