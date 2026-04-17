import os
import django
import random
from datetime import datetime, timedelta
from decimal import Decimal

# 1. 初始化 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from restaurant.models import Order
from django.utils import timezone

def generate_professional_data(count=12000):
    print(f"🚀 开始生成 {count} 条具备核心商业规律的数据...")
    
    # 准备基础菜品数据
    dish_pool = [
        {'name': '法兰基卷', 'category': '快餐', 'price': 15.0, 'weight': 30},
        {'name': '招牌三明治', 'category': '快餐', 'price': 18.0, 'weight': 25},
        {'name': '瓦达汉堡', 'category': '快餐', 'price': 12.0, 'weight': 20},
        {'name': '冰咖啡', 'category': '饮品', 'price': 10.0, 'weight': 15},
        {'name': '新鲜甘蔗汁', 'category': '饮品', 'price': 8.0, 'weight': 10},
    ]
    
    weights = [d['weight'] for d in dish_pool]
    pay_methods = ['在线支付', '现金']
    pay_weights = [85, 15]

    orders_to_create = []
    
    # ==========================================
    # 核心规律 1：周末效应（周末比工作日多 30% 订单）
    # ==========================================
    start_date = datetime(2022, 1, 1)
    end_date = datetime(2023, 12, 31)
    total_days = (end_date - start_date).days
    
    day_list = []
    day_weights = []
    for d in range(total_days + 1):
        current_day = start_date + timedelta(days=d)
        # .weekday() 中 5是周六，6是周日。周末权重设为 1.3 (比工作日 1.0 多30%)
        weight = 1.3 if current_day.weekday() >= 5 else 1.0 
        day_list.append(current_day)
        day_weights.append(weight)

    # ==========================================
    # 核心规律 2：精准的用餐高峰期（分钟级概率控制）
    # ==========================================
    minutes_in_day = []
    minute_weights = []
    for h in range(24):
        for m in range(60):
            minutes_in_day.append((h, m))
            time_val = h + m / 60.0
            # 精确锁定：中午（12:00-13:30）和 晚上（18:00-20:30）
            if 12.0 <= time_val <= 13.5:
                minute_weights.append(100) # 午餐高峰订单激增
            elif 18.0 <= time_val <= 20.5:
                minute_weights.append(120) # 晚餐高峰订单激增
            else:
                minute_weights.append(5)   # 其他时间生意清淡

    for i in range(count):
        # 1. 根据周末效应抽取日期
        random_day = random.choices(day_list, weights=day_weights)[0]
        
        # 2. 根据高峰效应抽取具体的时间（精确到分）
        h, m = random.choices(minutes_in_day, weights=minute_weights)[0]
        s = random.randint(0, 59)
        
        # 3. 确定售卖时段标签
        if 6 <= h < 11: period = "早晨"
        elif 11 <= h < 14: period = "中午"
        elif 14 <= h < 17: period = "下午"
        elif 17 <= h < 19: period = "傍晚"
        elif 19 <= h < 22: period = "晚上"
        else: period = "午夜"

        # 4. 随机选择菜品和数量
        dish = random.choices(dish_pool, weights=weights)[0]
        quantity = random.randint(1, 5)
        total_price = Decimal(str(dish['price'])) * quantity
        
        # 5. 组装订单对象并注入时区
        naive_dt = datetime.combine(random_day.date(), datetime.min.time().replace(hour=h, minute=m, second=s))
        aware_dt = timezone.make_aware(naive_dt)

        order = Order(
            order_number=f"CSV{10000 + i}",
            order_time=aware_dt,
            item_name=dish['name'],
            quantity=quantity,
            category=dish['category'],
            total_amount=total_price,
            payment_method=random.choices(pay_methods, weights=pay_weights)[0],
            time_of_sale=period
        )
        orders_to_create.append(order)

        # 批量极速存库
        if len(orders_to_create) >= 2000:
            Order.objects.bulk_create(orders_to_create)
            orders_to_create = []
            print(f"已生成 {i+1} 条...")

    # 存入剩余数据
    if orders_to_create:
        Order.objects.bulk_create(orders_to_create)

    print("✅ 完美！12000 条严格遵循【双高峰】和【周末效应】的数据已生成！")

if __name__ == "__main__":
    # 如果想覆盖之前的数据，可以取消下面这行的注释
    # Order.objects.all().delete() 
    generate_professional_data()