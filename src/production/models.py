from django.db import models
from django.utils import timezone
from inventory.models import Product

class ProductionOrder(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft (Planning)'),
        ('CONFIRMED', 'Confirmed (Queued)'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELED', 'Canceled'),
    ]

    order_number = models.CharField(max_length=20, unique=True, db_index=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        limit_choices_to={'nature': 'FG'}, # 只能生产成品
        related_name='production_orders',
        verbose_name="Finished Good"
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, help_text="Plan Quantity")

    start_date = models.DateField(default=timezone.now)
    due_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number} - {self.product.sku}"

class ProductionComponent(models.Model):
    """
    记录该工单实际需要/消耗的原料。
    虽然 BOM 存在，但我们在这里保存一份快照，以便后续追踪实际消耗（Variance）。
    """
    production_order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name='components')
    component = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='production_usage')

    # 理论需求量 (根据 BOM 计算)
    quantity_required = models.DecimalField(max_digits=10, decimal_places=4)
    # 实际消耗量 (生产完成后回填，默认为需求量)
    quantity_used = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    def __str__(self):
        return f"{self.production_order.order_number} req {self.component.sku}"

