from django.db import models
from django.utils import timezone

# 1. 菜品表 (保持不变，作为基础数据)
class Dish(models.Model):
    name = models.CharField(max_length=100, verbose_name="菜品名称")
    category = models.CharField(max_length=50, default="快餐", verbose_name="菜品分类", db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="菜品单价", db_index=True)
    description = models.TextField(blank=True, null=True, verbose_name="菜品简介")
    current_stock = models.IntegerField(default=50, verbose_name="当前库存")
    safety_stock = models.IntegerField(default=15, verbose_name="安全库存阈值")
    
    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "菜品"
        verbose_name_plural = "菜品列表"
        indexes = [
            models.Index(fields=['category', 'price']),
        ]

# 2. 订单主表 (移除了具体的菜品字段，仅保留订单属性)
class Order(models.Model):
    order_number = models.CharField(max_length=50, unique=True, verbose_name="订单编号")
    order_time = models.DateTimeField(default=timezone.now, verbose_name="下单时间", db_index=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="订单总额")
    
    # 商业维度属性
    payment_method = models.CharField(max_length=20, default="其他/现金", verbose_name="支付方式", db_index=True)
    time_of_sale = models.CharField(max_length=20, default="未知", verbose_name="售卖时段", db_index=True)

    def __str__(self):
        return self.order_number

    class Meta:
        verbose_name = "订单"
        verbose_name_plural = "订单列表"

# 3. 订单明细表 (核心重构：实现一个订单对应多个菜品)
class OrderItem(models.Model):
    # 建立与主订单的关联
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='items', 
        verbose_name="所属订单"
    )
    # 建立与菜品的关联
    dish = models.ForeignKey(
        Dish, 
        on_delete=models.CASCADE, 
        verbose_name="菜品"
    )
    # 该订单中该菜品的具体数量
    quantity = models.IntegerField(default=1, verbose_name="数量")
    # 记录下单时的单价，防止后续菜品调价导致历史订单数据异常
    price_at_order = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="下单时单价")

    class Meta:
        verbose_name = "订单明细"
        verbose_name_plural = "订单明细列表"

    def __str__(self):
        return f"{self.order.order_number} - {self.dish.name}"