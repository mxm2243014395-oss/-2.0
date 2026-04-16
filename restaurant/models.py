from django.db import models
from django.utils import timezone

class Order(models.Model):
    order_number = models.CharField(max_length=50, unique=True, verbose_name="订单编号")
    order_time = models.DateTimeField(default=timezone.now, verbose_name="下单时间", db_index=True)
    
    item_name = models.CharField(max_length=100, verbose_name="菜品名称", db_index=True)
    category = models.CharField(max_length=50, default="快餐", verbose_name="菜品分类")
    quantity = models.IntegerField(default=1, verbose_name="数量")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="交易总额")
    
    # === 本次新增的核心商业维度 ===
    payment_method = models.CharField(max_length=20, default="其他/现金", verbose_name="支付方式")
    time_of_sale = models.CharField(max_length=20, default="未知", verbose_name="售卖时段")

    class Meta:
        verbose_name = "订单"
        verbose_name_plural = "订单列表"
        # 联合索引，提升大屏按时间和菜品搜索的性能
        indexes = [
            models.Index(fields=['order_time', 'item_name']),
        ]

    def __str__(self):
        return f"{self.order_number} - {self.item_name}"