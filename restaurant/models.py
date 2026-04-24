from django.db import models
from django.utils import timezone

# 1. 菜品表 (保持不变)
class Dish(models.Model):
    name = models.CharField(max_length=100, verbose_name="菜品名称")
    category = models.CharField(max_length=50, default="快餐", verbose_name="菜品分类", db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="菜品单价", db_index=True)
    description = models.TextField(blank=True, null=True, verbose_name="菜品简介")

    # 核心库存字段
    current_stock = models.IntegerField(default=50, verbose_name="当前库存")
    safety_stock = models.IntegerField(default=15, verbose_name="安全库存阈值")
    
    class Meta:
        verbose_name = "菜品"
        verbose_name_plural = "菜品列表"
        indexes = [
            models.Index(fields=['category', 'price']),
        ]

    def __str__(self):
        return self.name

# 2. 订单主表 (瘦身版：只记录交易的宏观信息)
class Order(models.Model):
    order_number = models.CharField(max_length=50, unique=True, verbose_name="订单编号")
    order_time = models.DateTimeField(default=timezone.now, verbose_name="下单时间", db_index=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="交易总额")
    
    # 商业维度
    payment_method = models.CharField(max_length=20, default="其他/现金", verbose_name="支付方式", db_index=True)
    time_of_sale = models.CharField(max_length=20, default="未知", verbose_name="售卖时段", db_index=True)

    class Meta:
        verbose_name = "订单"
        verbose_name_plural = "订单列表"
        indexes = [
            models.Index(fields=['order_time']),
        ]

    def __str__(self):
        return self.order_number

# 3. 订单明细表 (全新抽取：解决多对多关系)
class OrderItem(models.Model):
    # on_delete=models.CASCADE: 订单删了，明细跟着删
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', verbose_name="所属订单")
    # on_delete=models.PROTECT: 只要这道菜被卖出过，就禁止在系统中被硬删除（防止财务账单报错）
    dish = models.ForeignKey(Dish, on_delete=models.PROTECT, verbose_name="包含菜品")
    
    quantity = models.IntegerField(default=1, verbose_name="数量")
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="下单单价")

    class Meta:
        verbose_name = "订单明细"
        verbose_name_plural = "订单明细列表"
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['dish']),
        ]

    @property
    def subtotal(self):
        """计算该明细行的小计金额"""
        return self.quantity * self.price_at_purchase

    def __str__(self):
        return f"{self.order.order_number} - {self.dish.name} x{self.quantity}"