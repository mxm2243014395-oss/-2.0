from django.db import models
from django.utils import timezone

# 1. 菜品表
class Dish(models.Model):
    name = models.CharField(max_length=100, verbose_name="菜品名称")
    category = models.CharField(max_length=50, default="快餐", verbose_name="菜品分类", db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="菜品单价", db_index=True)
    description = models.TextField(blank=True, null=True, verbose_name="菜品简介")

    class Meta:
        verbose_name = "菜品"
        verbose_name_plural = "菜品列表"
        indexes = [
            models.Index(fields=['category', 'price']),
        ]

# 2. 订单主表
class Order(models.Model):
    order_number = models.CharField(max_length=50, unique=True, verbose_name="订单编号")
    order_time = models.DateTimeField(default=timezone.now, verbose_name="下单时间", db_index=True)
    
    item_name = models.CharField(max_length=100, verbose_name="菜品名称", db_index=True)
    category = models.CharField(max_length=50, default="快餐", verbose_name="菜品分类")
    quantity = models.IntegerField(default=1, verbose_name="数量")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="交易总额")
    
    # 新增的商业维度
    payment_method = models.CharField(max_length=20, default="其他/现金", verbose_name="支付方式", db_index=True)
    time_of_sale = models.CharField(max_length=20, default="未知", verbose_name="售卖时段", db_index=True)

    class Meta:
        verbose_name = "订单"
        verbose_name_plural = "订单列表"
        indexes = [
            models.Index(fields=['order_time']),
            models.Index(fields=['item_name']),
            models.Index(fields=['order_time', 'item_name']),
        ]

# 3. 订单子项表 (如果你之前有这个，恢复它)
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, verbose_name="所属订单")
    # dish = models.ForeignKey(Dish, on_delete=models.CASCADE, verbose_name="菜品")
    # ... 其他字段 ...