from django.contrib import admin
from .models import ProductionOrder, ProductionComponent

class ProductionComponentInline(admin.TabularInline):
    model = ProductionComponent
    extra = 0
    readonly_fields = ('quantity_required',) # 建议初期设为只读，通过逻辑计算

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'product', 'quantity', 'status', 'start_date')
    list_filter = ('status', 'start_date')
    search_fields = ('order_number', 'product__sku')
    inlines = [ProductionComponentInline]
