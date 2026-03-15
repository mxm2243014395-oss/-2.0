from django.core.management.base import BaseCommand
from django.utils import timezone
from restaurant.models import Dish, Order, OrderItem
import random
from datetime import timedelta

class Command(BaseCommand):
    help = '生成极其逼真的餐厅运营测试数据（保证单品价格与总金额严格对齐）'

    def handle(self, *args, **options):
        self.stdout.write("正在清理旧数据...")
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Dish.objects.all().delete()

        # 解除 Django 强制将订单时间设为“当前时间”的限制
        order_time_field = Order._meta.get_field('order_time')
        order_time_field.auto_now_add = False
        order_time_field.auto_now = False

        # 1. 固定的菜品及价格库
        dishes_data = [
            {'name': '宫保鸡丁', 'category': '主菜', 'price': 25.00, 'weight': 80},
            {'name': '糖醋里脊', 'category': '主菜', 'price': 28.00, 'weight': 70},
            {'name': '米饭', 'category': '主食', 'price': 3.00, 'weight': 100},
            {'name': '鱼香肉丝', 'category': '主菜', 'price': 22.00, 'weight': 40},
            {'name': '麻婆豆腐', 'category': '主菜', 'price': 18.00, 'weight': 35},
            {'name': '清蒸鲈鱼', 'category': '主菜', 'price': 35.00, 'weight': 20},
            {'name': '炒面', 'category': '主食', 'price': 15.00, 'weight': 30},
            {'name': '可乐', 'category': '饮品', 'price': 5.00, 'weight': 50},
            {'name': '雪碧', 'category': '饮品', 'price': 5.00, 'weight': 40},
            {'name': '馒头', 'category': '主食', 'price': 2.00, 'weight': 5},
            {'name': '橙汁', 'category': '饮品', 'price': 8.00, 'weight': 8},
            {'name': '绿茶', 'category': '饮品', 'price': 6.00, 'weight': 5},
            {'name': '酸梅汤', 'category': '饮品', 'price': 7.00, 'weight': 3},
        ]

        Dish.objects.bulk_create([Dish(name=d['name'], category=d['category'], price=d['price']) for d in dishes_data])
        all_dishes = list(Dish.objects.all())
        dish_weights = [d['weight'] for d in dishes_data]

        days_to_generate = 120
        now = timezone.localtime(timezone.now())
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_to_generate)
        
        orders = []
        item_lists = []
        order_count = 0

        self.stdout.write("开始生成带有真实分布的订单数据...")

        for day_index in range(days_to_generate):
            current_date = start_date + timedelta(days=day_index)
            is_weekend = current_date.weekday() >= 5
            
            base_orders = random.randint(80, 120) if is_weekend else random.randint(30, 50)
            growth_trend = int((day_index / days_to_generate) * 20)
            daily_order_volume = base_orders + growth_trend

            for _ in range(daily_order_volume):
                order_time = self._generate_realistic_time(current_date)
                
                order = Order(
                    order_number=f'ORD{100000 + order_count}',
                    order_time=order_time,
                    total_amount=0
                )
                orders.append(order)
                
                items, total = self._generate_order_items(all_dishes, dish_weights, order)
                order.total_amount = total
                
                if items:
                    order.item_name = items[0].dish.name
                    order.item_price = items[0].dish.price
                    order.quantity = items[0].quantity
                
                item_lists.append(items)
                order_count += 1

        # 批量写入数据库
        batch_size = 1000
        created_orders = []
        for i in range(0, len(orders), batch_size):
            created_orders.extend(Order.objects.bulk_create(orders[i:i+batch_size]))

        all_items = []
        for created_order, items in zip(created_orders, item_lists):
            for item in items:
                item.order = created_order
            all_items.extend(items)

        for i in range(0, len(all_items), batch_size):
            OrderItem.objects.bulk_create(all_items[i:i+batch_size])

        self.stdout.write(self.style.SUCCESS(f'🎉 数据生成完毕！共生成 {order_count} 条严谨对齐的订单。'))

    def _generate_realistic_time(self, date):
        is_lunch = random.random() > 0.4  
        if is_lunch:
            hour_float = random.gauss(12.5, 0.8) 
            hour_float = max(10.5, min(14.5, hour_float)) 
        else:
            hour_float = random.gauss(18.5, 1.2) 
            hour_float = max(16.5, min(22.0, hour_float))
            
        hour = int(hour_float)
        minute = int((hour_float - hour) * 60)
        return date.replace(hour=hour, minute=minute, second=random.randint(0, 59))

    def _generate_order_items(self, all_dishes, dish_weights, order):
        """【核心修改区】：强制每笔订单只包含 1 种菜品，保证前台表格金额完美对齐"""
        items = []
        
        # 只随机抽取 1 种菜品
        chosen_dish = random.choices(all_dishes, weights=dish_weights, k=1)[0]
        # 数量随机 1 到 4 份
        quantity = random.randint(1, 4)
        
        item = OrderItem(
            order=order,
            dish=chosen_dish,
            quantity=quantity
        )
        items.append(item)
        
        # 订单总价严格等于：单价 * 数量
        total = chosen_dish.price * quantity
        
        return items, total