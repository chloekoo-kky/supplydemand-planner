from django.db import models
from django.db.models import Sum
from inventory.models import Product

class MarketDemand(models.Model):
    """
    [Input] 市场需求
    存储销售预测 (Forecast) 和实际销量 (Actual)，支持按月、按国家导入。
    """
    TYPE_CHOICES = [
        ('FORECAST', 'Sales Forecast'), # 预测值：用于驱动 MRP
        ('ACTUAL', 'Actual Sales'),     # 实际值：用于后期分析准确度
    ]

    period_date = models.DateField(help_text="需求月份 (通常存为该月1号)")
    country = models.CharField(max_length=50, db_index=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='market_demands',
        limit_choices_to={'nature': 'FG'} # 只预测成品
    )

    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    allocated_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="已锁定的库存数量 (Reserved Stock)"
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
        # 确保同一个国家、同一个月、同一个产品、同一种类型只有一条记录
        unique_together = ('period_date', 'country', 'product', 'demand_type')
        indexes = [
            models.Index(fields=['period_date', 'product']),
        ]
        verbose_name = "Market Demand"

    def __str__(self):
        status = "PENDING"
        if self.shipped_date: status = "SHIPPED"
        elif self.allocated_qty > 0: status = f"ALLOCATED ({self.allocated_qty})" # 更新显示逻辑
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
    calculation_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['suggested_start_date']

    def __str__(self):
        return f"{self.product.sku}: {self.suggested_qty}"
