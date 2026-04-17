import os
import django
import random
from datetime import datetime, timedelta, time
from decimal import Decimal

# 1. 初始化 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from restaurant.models import Order
from django.utils import timezone

def generate_high_volume_data():
    print("🚀 开始生成【高销量真实商家】级别的海量数据...")

    # ==========================================
    # 核心规律 1：完美复刻的菜品销量与分类占比
    # 巧妙的权重设计：
    # 饮品总权重(315) vs 快餐总权重(655) ≈ 32% vs 68%
    # 但单品排名：冰咖啡(160) > 甘蔗汁(150) > 脆球(145)... 饮品成功霸榜前二！
    # ==========================================
    dish_pool = [
        # 饮品类 (霸榜冠亚军)
        {'name': '冰咖啡', 'category': '饮品', 'price': 15.0, 'weight': 160},
        {'name': '新鲜甘蔗汁', 'category': '饮品', 'price': 12.0, 'weight': 150},
        
        # 快餐类 (种类多，总占比达到 68%)
        {'name': '脆球点心', 'category': '快餐', 'price': 10.0, 'weight': 145},
        {'name': '法兰基卷', 'category': '快餐', 'price': 18.0, 'weight': 135},
        {'name': '瓦达汉堡', 'category': '快餐', 'price': 15.0, 'weight': 130},
        {'name': '招牌三明治', 'category': '快餐', 'price': 20.0, 'weight': 125},
        {'name': '咖喱土豆球', 'category': '快餐', 'price': 12.0, 'weight': 120},
        
        # 专门保留用于“滞销菜品榜”测试的垫底菜品
        {'name': '玉米汁', 'category': '饮品', 'price': 8.0, 'weight': 5},   # 极难卖
        {'name': '墨西哥卷饼', 'category': '快餐', 'price': 22.0, 'weight': 0},    # 绝对 0 销量
    ]

    weights = [d['weight'] for d in dish_pool]
    
    # ==========================================
    # 核心规律 2：复刻支付方式占比
    # 现金(48.2%), 在线(41.4%), 其他(10.4%)
    # ==========================================
    pay_methods = ['现金', '在线支付', '其他']
    pay_weights = [482, 414, 104]

    orders_to_create = []
    total_created = 0

    # 严格定义时间范围：2025年下半年 (7月1日 到 12月31日)
    start_date = datetime(2025, 7, 1).date()
    end_date = datetime(2025, 12, 31).date()
    total_days = (end_date - start_date).days + 1

    print(f"📅 总计 {total_days} 天，预计将生成约 6万 条订单...")

    # 遍历每一天生成订单
    for day_offset in range(total_days):
        current_day = start_date + timedelta(days=day_offset)

        # 核心规律 3：周末效应（周末大爆发，工作日稳定）
        is_weekend = current_day.weekday() >= 5
        if is_weekend:
            daily_orders_count = random.randint(280, 450) # 周末生意极其火爆
        else:
            daily_orders_count = random.randint(100, 250) # 工作日保持高流水

        # 核心规律 4：双高峰客流分配
        for _ in range(daily_orders_count):
            rand_val = random.random()
            
            # 精确控制时间落点
            if rand_val < 0.40:
                # 40% 的订单在午餐高峰 (11:30 - 13:59)
                h = random.choice([11, 12, 13])
                m = random.randint(30 if h == 11 else 0, 59)
            elif rand_val < 0.85:
                # 45% 的订单在晚餐高峰 (17:30 - 20:59)
                h = random.choice([17, 18, 19, 20])
                m = random.randint(30 if h == 17 else 0, 59)
            else:
                # 15% 散落于其他时段 (早餐、下午茶、夜宵)
                h = random.choice([8, 9, 10, 14, 15, 16, 21, 22])
                m = random.randint(0, 59)

            s = random.randint(0, 59)

            # 确定售卖时段标签
            if 6 <= h < 11: period = "早晨"
            elif 11 <= h < 14: period = "中午"
            elif 14 <= h < 17: period = "下午"
            elif 17 <= h < 21: period = "傍晚"
            elif 21 <= h < 23: period = "晚上"
            else: period = "午夜"

            # 随机菜品与购买数量
            dish = random.choices(dish_pool, weights=weights)[0]
            quantity = random.choices([1, 2, 3, 4, 5], weights=[40, 30, 15, 10, 5])[0]
            total_price = Decimal(str(dish['price'])) * quantity

            naive_dt = datetime.combine(current_day, time(h, m, s))
            aware_dt = timezone.make_aware(naive_dt)

            order = Order(
                order_number=f"ORD{current_day.strftime('%y%m%d')}{total_created:04d}",
                order_time=aware_dt,
                item_name=dish['name'],
                quantity=quantity,
                category=dish['category'],
                total_amount=total_price,
                payment_method=random.choices(pay_methods, weights=pay_weights)[0],
                time_of_sale=period
            )
            orders_to_create.append(order)
            total_created += 1

            # 加大批量写入阈值，保障性能
            if len(orders_to_create) >= 5000:
                Order.objects.bulk_create(orders_to_create)
                orders_to_create = []
                print(f"⏳ 已成功写入 {total_created} 条订单...")

    # 写入最后残余的订单
    if orders_to_create:
        Order.objects.bulk_create(orders_to_create)
        print(f"⏳ 已成功写入 {total_created} 条订单...")

    print(f"✅ 完美！总计 {total_created} 条高销量商业数据已安全写入 MySQL！")

if __name__ == "__main__":
    print("🧹 正在清空旧的测试数据，以防数据污染...")
    Order.objects.all().delete() 
    generate_high_volume_data()