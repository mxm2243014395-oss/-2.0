import os
import sys
import django
import random
import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal

# 1. 初始化 Django 环境
project_root = r'E:\VScode Files\-2.0'
if project_root not in sys.path:
    sys.path.insert(0, project_root)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from restaurant.models import Order, Dish, OrderItem
from django.utils import timezone

def generate_real_restaurant_data():
    # 设定 2023 全年
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2023, 12, 31)
    total_days = (end_date - start_date).days
    
    print(f"🚀 启动【真实餐饮商业模型】引擎：正在生成 2023 全年高仿真流水...")
    
    # ==========================================
    # 规律 1：符合原数据集（快餐/饮品）的真实定价
    # ==========================================
    dish_pool = [
        {'name': '冰咖啡', 'category': '饮品', 'price': 10.0, 'weight': 60},
        {'name': '新鲜甘蔗汁', 'category': '饮品', 'price': 8.0, 'weight': 50},
        {'name': '招牌三明治', 'category': '快餐', 'price': 18.0, 'weight': 30},
        {'name': '法兰基卷', 'category': '快餐', 'price': 15.0, 'weight': 40},
        {'name': '脆球点心', 'category': '快餐', 'price': 12.0, 'weight': 50},
        {'name': '咖喱土豆球', 'category': '快餐', 'price': 10.0, 'weight': 35},
        {'name': '瓦达汉堡', 'category': '快餐', 'price': 12.0, 'weight': 35},
    ]
    weights = [d['weight'] for d in dish_pool]
    pay_methods = ['在线支付', '现金', '其他']
    pay_weights = [70, 20, 10]

    # ==========================================
    # 规律 2：精准的营业时段分布 (09:00 - 23:00)
    # ==========================================
    minutes_in_day = []
    minute_weights = []
    for h in range(24):
        for m in range(60):
            if h < 9 or h >= 23:
                continue 
            minutes_in_day.append((h, m))
            time_val = h + m / 60.0
            # 午餐和晚餐时段客流增加，其余时间平稳
            if 11.5 <= time_val <= 13.5 or 17.5 <= time_val <= 20.0:
                minute_weights.append(110)
            else:
                minute_weights.append(90)

    # ==========================================
    # 规律 3：宏观经济周期（淡旺季系数）
    # ==========================================
    month_multiplier = {
        1: 0.85, 2: 0.90, 3: 1.00, 4: 1.05, 
        5: 1.00, 6: 1.15, 7: 1.25, 8: 1.20, 
        9: 0.95, 10: 1.05, 11: 1.15, 12: 1.35 
    }

    export_rows = []
    total_generated = 0
    total_revenue_simulated = 0 
    
    # 清空数据库旧数据（Order 删除会级联删除其 OrderItem）
    Order.objects.all().delete()

    # 确保菜品主数据存在，返回 name -> Dish 实例映射
    dish_map = {}
    for dish_def in dish_pool:
        dish_obj, _ = Dish.objects.get_or_create(
            name=dish_def['name'],
            defaults={
                'category': dish_def['category'],
                'price': Decimal(str(dish_def['price'])),
                'current_stock': 200,
                'safety_stock': 30,
                'description': f"{dish_def['category']}（自动生成）",
            }
        )
        # 若历史数据中价格/分类不一致，按脚本标准同步一次
        dirty = False
        target_price = Decimal(str(dish_def['price']))
        if dish_obj.category != dish_def['category']:
            dish_obj.category = dish_def['category']
            dirty = True
        if dish_obj.price != target_price:
            dish_obj.price = target_price
            dirty = True
        if dirty:
            dish_obj.save(update_fields=['category', 'price'])
        dish_map[dish_def['name']] = dish_obj

    for d in range(total_days + 1):
        current_day = start_date + timedelta(days=d)
        is_weekend = current_day.weekday() >= 5
        current_month = current_day.month
        month_factor = month_multiplier[current_month]
        
        # ==========================================
        # 规律 4：周中/周末的 20%-30% 黄金波动法则
        # ==========================================
        if is_weekend:
            # 周末基础均值约 70 单
            min_base = int(65 / month_factor)
            max_base = int(95 / month_factor)
            base_count = random.randint(min_base, max_base)
        else:
            # 周中基础均值约 55 单 (周末比周中刚好高出 27%)
            min_base = int(45 / month_factor)
            max_base = int(65 / month_factor)
            base_count = random.randint(min_base, max_base)
            
        # 叠加月份淡旺季
        base_count = int(base_count * month_factor)
        
        # ==========================================
        # 规律 5：黑天鹅事件（真实世界阻力）
        # ==========================================
        event_roll = random.random()
        if event_roll < 0.05:
            base_count = int(base_count * 1.15) # 5% 遇到周边活动微爆单
        elif event_roll > 0.92:
            base_count = int(base_count * 0.7)  # 8% 遇到恶劣天气客流锐减
            
        # 设定绝对安全边界，防止数值失控
        if is_weekend:
            daily_count = min(110, max(30, base_count)) 
        else:
            daily_count = min(69, max(20, base_count))  
        
        for i in range(daily_count):
            h, m = random.choices(minutes_in_day, weights=minute_weights)[0]
            s = random.randint(0, 59) 
            
            if 9 <= h < 11: period = "早晨"
            elif 11 <= h < 14: period = "午餐"
            elif 14 <= h < 17: period = "下午茶"
            elif 17 <= h < 21: period = "晚餐"
            else: period = "午夜"

            dish = random.choices(dish_pool, weights=weights)[0]
            
            # ==========================================
            # 规律 6：80/20 的消费者画像分布
            # ==========================================
            if random.random() < 0.80:
                quantity = random.randint(1, 2)  # 80% 是散客解馋
            else:
                quantity = random.randint(3, 5)  # 20% 是情侣/朋友聚餐
            
            total_price = Decimal(str(dish['price'])) * quantity
            total_revenue_simulated += total_price
            
            naive_dt = datetime.combine(current_day.date(), datetime.min.time().replace(hour=h, minute=m, second=s))
            aware_dt = timezone.make_aware(naive_dt)
            order_sn = f"ORD{current_day.strftime('%Y%m%d')}{str(i+1).zfill(3)}"

            payment_method = random.choices(pay_methods, weights=pay_weights)[0]
            order = Order.objects.create(
                order_number=order_sn,
                order_time=aware_dt,
                total_amount=total_price,
                payment_method=payment_method,
                time_of_sale=period
            )
            OrderItem.objects.create(
                order=order,
                dish=dish_map[dish['name']],
                quantity=quantity,
                price_at_purchase=Decimal(str(dish['price'])),
            )
            export_rows.append({
                'order_number': order_sn,
                'order_time': aware_dt.replace(tzinfo=None),
                'item_name': dish['name'],
                'quantity': quantity,
                'category': dish['category'],
                'total_amount': float(total_price),
                'payment_method': payment_method,
                'time_of_sale': period,
            })
            total_generated += 1

            if total_generated % 2000 == 0:
                print(f"   ⏳ 进度：{current_day.date()}，当前累计 {total_generated} 单")

    avg_order_value = total_revenue_simulated / total_generated if total_generated > 0 else 0

    # 导出为 Excel 到当前脚本所在目录（-2.0data）
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(output_dir, 'generated_orders_2023.xlsx')
    export_df = pd.DataFrame(export_rows)
    if not export_df.empty:
        export_df = export_df.sort_values(by='order_time').reset_index(drop=True)
    export_df.to_excel(output_file, index=False)

    print(f"\n✅ 数据生成完美收官！")
    print(f"📊 全年总单量：{total_generated} 单（日均约 {int(total_generated/365)} 单）")
    print(f"💰 全年总营业额：约 ¥{total_revenue_simulated:,.2f}")
    print(f"🎯 平均客单价：约 ¥{avg_order_value:.2f} /单")
    print(f"📁 Excel 已导出：{output_file}")

if __name__ == "__main__":
    generate_real_restaurant_data()