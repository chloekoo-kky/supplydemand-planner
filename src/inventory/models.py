from django.db import models


class Supplier(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    contact_person = models.CharField(max_length=100, blank=True, help_text="联系人")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name

class ProductGroup(models.Model):
    """
    用户自定义的分组 (对应界面上的 Tabs)
    例如: "Urgent", "New Arrivals"
    """
    NATURE_CHOICES = [
        ('RAW', 'Ingredient / Raw Material'),
        ('PKG', 'Packaging Material'),
        ('FG',  'Finished Product'),
    ]

    # 新增: 必须指定这个组属于哪种类型 (比如 'RAW' 的组只显示在 Raw Material 页面)
    nature = models.CharField(max_length=10, choices=NATURE_CHOICES, db_index=True)
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.get_nature_display()} - {self.name}"

class Product(models.Model):
    """
    物料主数据 (Master Data)
    用于存储从 MRP/ERP 导出的基础信息，以及 Planner 设定的计划参数。
    """

    NATURE_CHOICES = [
        ('RAW', 'Ingredient / Raw Material'),  # 原料
        ('PKG', 'Packaging Material'),         # 包材
        ('FG',  'Finished Product'),           # 成品
    ]

    sku = models.CharField(max_length=50, unique=True, db_index=True, help_text="物料编码 (SKU)")
    description = models.CharField(max_length=255, blank=True, help_text="物料描述")
    uom = models.CharField(max_length=10, default='EA', help_text="单位 (Unit of Measure)")
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL, # 如果删除了供应商，产品保留，但 supplier 字段变空
        null=True,
        blank=True,
        related_name='products',
        help_text="供应商"
    )

    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="成本价")

    group = models.ForeignKey(
        ProductGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products'
    )
    sort_order = models.PositiveIntegerField(default=0)

    estimated_daily_usage = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="预估日均消耗量 (用于计算库存覆盖天数)"
    )
    safety_stock_days = models.IntegerField(default=14, help_text="目标安全库存天数")
    moq = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="最小起订量 (MOQ)")
    lead_time_days = models.IntegerField(default=30, help_text="采购/生产前置时间 (Lead Time)")

    nature = models.CharField(
        max_length=10,
        choices=NATURE_CHOICES,
        default='FG',
        db_index=True,
        verbose_name="Product Nature" # 前端显示 "Product Nature"
    )

    category = models.CharField(
        max_length=50,
        default='General',
        db_index=True,  # 加索引，因为你会经常按组筛选
        help_text="e.g. Syrups, Sauces, Purees"
    )

    unit_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Unit Weight (kg)"
    )
    unit_volume = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="单品体积 (L)"
    )
    is_temporary = models.BooleanField(
        default=False,
        help_text="是否为导入时因数据冲突产生的临时产品"
    )

    @property
    def total_weight_display(self):
        """
        计算逻辑: 库存数量 * 单品重量
        注意: current_stock 是我们在 views.py 里通过 annotate 加上去的
        """
        stock = getattr(self, 'current_stock', 0) or 0
        weight = self.unit_weight or 0

        if weight > 0 and stock > 0:
            total = stock * weight
            # 返回格式化好的字符串: "450.00 kg"
            return f"{total:,.2f} kg"
        return None

    @property
    def total_volume_display(self):
        """
        计算逻辑: 库存数量 * 单品体积
        """
        stock = getattr(self, 'current_stock', 0) or 0
        vol = self.unit_volume or 0

        if vol > 0 and stock > 0:
            total = stock * vol
            return f"{total:,.2f} L"
        return None

    def __str__(self):
        prefix = "[TEMP] " if self.is_temporary else ""
        return f"{prefix}{self.sku} - {self.description}"

class ProductAlias(models.Model):
    product = models.ForeignKey(Product, related_name='aliases', on_delete=models.CASCADE)
    alias_name = models.CharField(max_length=255, db_index=True)

    class Meta:
        unique_together = ('product', 'alias_name')

    def __str__(self):
        return f"{self.alias_name} -> {self.product.sku}"

class RawMaterialManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(nature='RAW')

class RawMaterial(Product):
    objects = RawMaterialManager()

    class Meta:
        proxy = True  # 关键：告诉 Django 不要创建新表
        verbose_name = "Raw Material"
        verbose_name_plural = "Raw Materials"

    def save(self, *args, **kwargs):
        self.nature = 'RAW'  # 自动设置类型
        super().save(*args, **kwargs)

class PackagingMaterialManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(nature='PKG')

class PackagingMaterial(Product):
    objects = PackagingMaterialManager()

    class Meta:
        proxy = True
        verbose_name = "Packaging Material"
        verbose_name_plural = "Packaging Materials"

    def save(self, *args, **kwargs):
        self.nature = 'PKG'
        super().save(*args, **kwargs)

class FinishedGoodManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(nature='FG')

class FinishedGoods(Product):
    objects = FinishedGoodManager()

    class Meta:
        proxy = True
        verbose_name = "Finished Good"
        verbose_name_plural = "Finished Goods"

    def save(self, *args, **kwargs):
        self.nature = 'FG'
        super().save(*args, **kwargs)


class InventorySnapshot(models.Model):
    """
    库存快照 (Transaction Data)
    记录每一天、每一个 SKU 的库存水平。这是做 Forecast 的基础。
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='snapshots')
    snapshot_date = models.DateField(help_text="数据快照日期 (通常是导入当天)")

    # 核心库存数据
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=2, help_text="现有库存 (SOH)")
    quantity_on_order = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="在途库存 (PO Issued)")
    quantity_reserved = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="已预留库存 (Reserved)")

    class Meta:
        # 复合唯一索引：防止同一天、同一个 SKU 导入两次
        unique_together = ('product', 'snapshot_date')
        # 索引优化：经常会按日期查询库存
        indexes = [
            models.Index(fields=['snapshot_date', 'product']),
        ]
        ordering = ['-snapshot_date']

    def __str__(self):
        return f"{self.snapshot_date} - {self.product.sku}: {self.quantity_on_hand}"

class BillOfMaterial(models.Model):
    """
    Bill of Materials (BOM) / Recipe
    Links a Finished Good (Parent) to its Raw Materials/Packaging (Components).
    """
    # The Parent Product (must be FG)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='bom_lines',
        limit_choices_to={'nature': 'FG'},
        verbose_name="Finished Good"
    )

    # The Component (can be RAW or PKG)
    component = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='used_in_boms',
        limit_choices_to=~models.Q(nature='FG'), # Component cannot be FG (avoid loops for now)
        verbose_name="Component"
    )

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=1,
        help_text="Qty required to make 1 unit of FG"
    )

    class Meta:
        unique_together = ('product', 'component')
        verbose_name = "Bill of Material"
        verbose_name_plural = "Bill of Materials"

    def __str__(self):
        return f"{self.product.sku} needs {self.quantity:g} x {self.component.sku}"
