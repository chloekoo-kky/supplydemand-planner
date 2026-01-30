# src/production/admin.py
from django.contrib import admin
from .models import ProductionOrder, ProductionComponent

class ProductionComponentInline(admin.TabularInline):
    model = ProductionComponent
    extra = 0
    readonly_fields = ('quantity_required',)

@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    # Added 'due_date' to the list display
    list_display = ('order_number', 'product', 'quantity', 'status', 'start_date', 'due_date')

    # Added 'due_date' to filters for easier tracking
    list_filter = ('status', 'start_date', 'due_date')

    # Allows for drill-down navigation by date at the top of the admin page
    date_hierarchy = 'due_date'

    search_fields = ('order_number', 'product__sku')
    inlines = [ProductionComponentInline]

    # Ensures dates are editable within the detail view
    fields = (
        'order_number', 'product', 'quantity',
        'status', 'start_date', 'due_date', 'notes'
    )
