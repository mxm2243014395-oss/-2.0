from django.core.management.base import BaseCommand
from restaurant.models import Order, Dish, OrderItem

class Command(BaseCommand):
    help = '同步Order数据到OrderItem和Dish表'

    def handle(self, *args, **options):
        # 删除现有OrderItem以避免重复
        OrderItem.objects.all().delete()

        orders = Order.objects.exclude(item_name__isnull=True).exclude(item_name='')

        for order in orders:
            # 创建或获取Dish
            dish, created = Dish.objects.get_or_create(
                name=order.item_name,
                defaults={
                    'category': '未知',
                    'price': order.item_price
                }
            )
            if created:
                self.stdout.write(f'创建新菜品: {dish.name}')

            # 创建OrderItem
            OrderItem.objects.create(
                order=order,
                dish=dish,
                quantity=order.quantity
            )

        self.stdout.write(self.style.SUCCESS(f'成功同步 {orders.count()} 个订单的明细数据'))