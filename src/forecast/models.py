from django.db import models
from django.db.models import Sum
from inventory.models import Product

class OutboundShipment(models.Model):
    """
    [Container] 代表一个出货柜或批次 (Shipment/Container)
    """
    STATUS_CHOICES = [
        ('PLANNING', 'Planning'), # 正在拼柜
        ('SHIPPED', 'Shipped'),   # 已离港
        ('ARRIVED', 'Arrived'),   # 已到港
    ]

    reference = models.CharField(max_length=50, unique=True, help_text="Container No. or Booking Ref")
    etd = models.DateField(help_text="Estimated Time of Departure")

    destination = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Optional: Restrict this shipment to a specific Country/Customer."
    )

    status = models.CharField(max_length=20, default='PLANNING', choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        dest_str = f" -> {self.destination}" if self.destination else ""
        return f"{self.reference} ({self.etd}){dest_str}"

class MarketDemand(models.Model):
    """
    [Input] 市场需求
    存储销售预测 (Forecast) 和实际销量 (Actual)，支持按月、按国家导入。
    """
    TYPE_CHOICES = [
        ('FORECAST', 'Sales Forecast'),
        ('ACTUAL', 'Actual Sales'),
    ]

    period_date = models.DateField(help_text="需求月份 (通常存为该月1号)")
    country = models.CharField(max_length=50, db_index=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='market_demands',
        limit_choices_to={'nature': 'FG'}
    )

    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # === Allocation & Shipping ===
    allocated_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="已锁定的库存数量 (Reserved Stock)"
    )

    # [NEW] 关联到具体的出货批次
    shipment = models.ForeignKey(
        OutboundShipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='demands',
        help_text="所属的出货柜/批次"
    )

    demand_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='FORECAST', db_index=True)
    is_allocated = models.BooleanField(
        default=False,
        help_text="[Actual Only] Stock has been reserved/allocated for this demand."
    )

    shipped_date = models.DateField(
        null=True, blank=True,
        help_text="实际出仓日期 (填写后代表库存已扣除)"
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('period_date', 'country', 'product', 'demand_type')
        indexes = [
            models.Index(fields=['period_date', 'product']),
        ]
        verbose_name = "Market Demand"

    def __str__(self):
        status = "PENDING"
        if self.shipped_date: status = "SHIPPED"
        elif self.allocated_qty > 0: status = f"ALLOCATED ({self.allocated_qty})"
        return f"[{status}] {self.country} {self.period_date:%Y-%m} - {self.product.sku}"


class ForecastPlan(models.Model):
    """
    [Container] MRP 计算结果容器
    每次运行 MRP 都会生成一个 Plan，包含多个 Entry。
    """
    name = models.CharField(max_length=100, unique=True)
    target_month = models.DateField(help_text="计划针对的月份")
    created_at = models.DateTimeField(auto_now_add=True)

    # 状态锁：如果已经转成 Production Order，可以锁住不让修改
    is_locked = models.BooleanField(default=False)

    def __str__(self):
        return self.name

class ForecastEntry(models.Model):
    """
    [Output] MRP 建议行项目
    系统计算出的“净需求”，建议你生产什么、多少、什么时候开始。
    """
    plan = models.ForeignKey(ForecastPlan, on_delete=models.CASCADE, related_name='entries')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    # 核心 MRP 建议
    suggested_qty = models.DecimalField(max_digits=10, decimal_places=2, help_text="MRP 建议生产量")

    # 时间节点
    eta_date = models.DateField(help_text="目标入库日期 (满足需求的时间)")
    suggested_start_date = models.DateField(help_text="建议开工日期 (ETA - LeadTime)")

    # 状态追踪 (核心功能：转单)
    production_order = models.OneToOneField(
        'production.ProductionOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='forecast_source',
        help_text="关联的生产工单"
    )

    # 逻辑备注 (解释为什么需要生产这么多，例如：Demand 500 - Stock 100 = 400)
    calculation_note = models.TextField(blank=True, help_text="存储详细的 MRP 计算逻辑 (JSON)")

    class Meta:
        ordering = ['suggested_start_date']

    def __str__(self):
        return f"{self.product.sku}: {self.suggested_qty}"
