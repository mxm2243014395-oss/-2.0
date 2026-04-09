from django.db import models

class Dish(models.Model):
    name = models.CharField(max_length=100, verbose_name='菜品名称')
    category = models.CharField(max_length=50, verbose_name='分类')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='单价')

    current_stock = models.IntegerField(default=50, verbose_name='当前库存')
    safety_stock = models.IntegerField(default=15, verbose_name='安全库存阈值')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = '菜品'
        verbose_name_plural = '菜品'

class Order(models.Model):
    order_number = models.CharField(max_length=50, unique=True, verbose_name='订单编号')
    order_time = models.DateTimeField(auto_now_add=True, verbose_name='下单时间')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='订单总金额')
    # 临时添加用于同步的字段
    item_name = models.CharField(max_length=100, verbose_name='菜品名称', blank=True, null=True)
    item_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='单价', blank=True, null=True)
    quantity = models.PositiveIntegerField(verbose_name='数量', blank=True, null=True)

    def __str__(self):
        return self.order_number

    class Meta:
        verbose_name = '订单'
        verbose_name_plural = '订单'

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, verbose_name='订单')
    dish = models.ForeignKey(Dish, on_delete=models.CASCADE, verbose_name='菜品')
    quantity = models.PositiveIntegerField(verbose_name='购买数量')

    def __str__(self):
        return f"{self.order.order_number} - {self.dish.name}"

    class Meta:
        verbose_name = '订单明细'
        verbose_name_plural = '订单明细'