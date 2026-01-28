from django.contrib import admin
from .models import OutboundShipment, MarketDemand, ForecastPlan, ForecastEntry

# 1. 定义 Inline，以便在 Shipment 页面直接看到装了哪些货
class MarketDemandInline(admin.TabularInline):
    model = MarketDemand
    fields = ('product', 'country', 'quantity', 'allocated_qty', 'demand_type', 'is_allocated')
    # 让大部分字段只读，防止在 Shipment 页面意外修改需求原始数据
    readonly_fields = ('product', 'country', 'quantity', 'demand_type', 'is_allocated')
    extra = 0
    can_delete = False
    fk_name = 'shipment'
    show_change_link = True # 允许点击跳转到 Demand 详情

@admin.register(OutboundShipment)
class OutboundShipmentAdmin(admin.ModelAdmin):
    list_display = ('reference', 'etd', 'destination', 'status', 'total_items', 'created_at')
    list_filter = ('status', 'etd', 'destination')
    search_fields = ('reference', 'destination')
    date_hierarchy = 'etd'
    inlines = [MarketDemandInline]

    def total_items(self, obj):
        return obj.demands.count()
    total_items.short_description = "Items Loaded"

# 2. 注册其他相关模型，方便调试
@admin.register(MarketDemand)
class MarketDemandAdmin(admin.ModelAdmin):
    list_display = ('product', 'country', 'period_date', 'quantity', 'allocated_qty', 'shipment', 'demand_type')
    list_filter = ('demand_type', 'period_date', 'country', 'is_allocated', 'shipment')
    search_fields = ('product__sku', 'country', 'shipment__reference')
    autocomplete_fields = ('shipment', 'product') # 提升加载速度

@admin.register(ForecastPlan)
class ForecastPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_month', 'is_locked', 'created_at')
    list_filter = ('target_month', 'is_locked')

@admin.register(ForecastEntry)
class ForecastEntryAdmin(admin.ModelAdmin):
    list_display = ('plan', 'product', 'suggested_qty', 'eta_date', 'production_order')
    list_filter = ('plan', 'eta_date')
    search_fields = ('product__sku', 'plan__name')
