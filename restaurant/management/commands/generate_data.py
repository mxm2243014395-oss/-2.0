from django.core.management.base import BaseCommand
from django.utils import timezone
from ...models import Dish, Order, OrderItem
import random
from datetime import datetime, timedelta

class Command(BaseCommand):
    help = '生成测试数据：10-15种菜品和2000条订单及明细'

    def handle(self, *args, **options):
        # 删除现有数据
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Dish.objects.all().delete()

        # 创建菜品数据
        dishes_data = [
            {'name': '宫保鸡丁', 'category': '主菜', 'price': 25.00},
            {'name': '鱼香肉丝', 'category': '主菜', 'price': 22.00},
            {'name': '麻婆豆腐', 'category': '主菜', 'price': 18.00},
            {'name': '糖醋里脊', 'category': '主菜', 'price': 28.00},
            {'name': '清蒸鲈鱼', 'category': '主菜', 'price': 35.00},
            {'name': '米饭', 'category': '主食', 'price': 3.00},
            {'name': '馒头', 'category': '主食', 'price': 2.00},
            {'name': '炒面', 'category': '主食', 'price': 15.00},
            {'name': '可乐', 'category': '饮品', 'price': 5.00},
            {'name': '雪碧', 'category': '饮品', 'price': 5.00},
            {'name': '橙汁', 'category': '饮品', 'price': 8.00},
            {'name': '绿茶', 'category': '饮品', 'price': 6.00},
            {'name': '酸梅汤', 'category': '饮品', 'price': 7.00},
        ]

        # 批量创建菜品
        Dish.objects.bulk_create([Dish(**data) for data in dishes_data])
        all_dishes = list(Dish.objects.all())

        # 生成日期范围
        start_date = timezone.now() - timedelta(days=365)
        workdays = []
        weekends = []
        for days_ago in range(365):
            date = start_date + timedelta(days=days_ago)
            if date.weekday() < 5:  # 周一到周五
                workdays.append(days_ago)
            else:
                weekends.append(days_ago)

        # 准备订单和明细数据
        orders = []
        item_lists = []
        order_count = 0

        # 生成工作日订单 (800条)
        for _ in range(800):
            days_ago = random.choice(workdays)
            date = start_date + timedelta(days=days_ago)
            order_time = self._generate_order_time(date)
            order = Order(
                order_number=f'ORD{100000 + order_count}',
                order_time=order_time,
                total_amount=0  # 稍后计算
            )
            orders.append(order)
            items, total = self._generate_order_items(all_dishes, order)
            order.total_amount = total
            if items:
                order.item_name = items[0].dish.name
                order.item_price = items[0].dish.price
                order.quantity = items[0].quantity
            item_lists.append(items)
            order_count += 1

        # 生成周末订单 (1200条)
        for _ in range(1200):
            days_ago = random.choice(weekends)
            date = start_date + timedelta(days=days_ago)
            order_time = self._generate_order_time(date)
            order = Order(
                order_number=f'ORD{100000 + order_count}',
                order_time=order_time,
                total_amount=0
            )
            orders.append(order)
            items, total = self._generate_order_items(all_dishes, order)
            order.total_amount = total
            if items:
                order.item_name = items[0].dish.name
                order.item_price = items[0].dish.price
                order.quantity = items[0].quantity
            item_lists.append(items)
            order_count += 1

        # 批量创建订单
        created_orders = Order.objects.bulk_create(orders)

        # 批量创建订单明细
        all_items = []
        for created_order, items in zip(created_orders, item_lists):
            for item in items:
                item.order = created_order
            all_items.extend(items)

        OrderItem.objects.bulk_create(all_items)

        self.stdout.write(self.style.SUCCESS('成功生成测试数据：13种菜品，2000条订单'))

    def _generate_order_time(self, date):
        """生成订单时间，集中在午餐和晚餐时段"""
        is_lunch = random.choice([True, False])
        if is_lunch:
            hour = random.randint(11, 12)
        else:
            hour = random.randint(17, 19)
        minute = random.randint(0, 59)
        return date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _generate_order_items(self, all_dishes, order):
        """生成订单明细"""
        num_items = random.randint(1, 5)
        items = []
        total = 0
        for _ in range(num_items):
            dish = random.choice(all_dishes)
            quantity = random.randint(1, 3)
            item = OrderItem(
                order=order,  # 暂时设为order对象，稍后更新为created_order
                dish=dish,
                quantity=quantity
            )
            items.append(item)
            total += dish.price * quantity
        return items, total