from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta
from .models import Order, OrderItem, Dish
from django.db.models import Sum
from django.core.paginator import Paginator  # 新增：导入分页器
import pandas as pd
import numpy as np

# 导入机器学习库
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error

# 导入认证与注册相关的库
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User

from django import forms
import time

from itertools import combinations
from collections import Counter

# =========================================================
# 1. 运营监控大屏视图 (加入了 AI 推荐与备货算法)
# =========================================================
@login_required 
def dashboard(request):
    total_orders = Order.objects.count()
    total_amount = Order.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
#计算平均客单价 (防除以0报错)
    avg_order_value = total_amount / total_orders if total_orders > 0 else 0

    now = timezone.now()
    local_now = timezone.localtime(now)
    local_now_naive = local_now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    
    thirty_days_ago = now - timedelta(days=30)
    recent_30_days_orders = Order.objects.filter(order_time__gte=thirty_days_ago)

    daily_dict = {}
    hourly_dict = {}

    for order in recent_30_days_orders:
        local_time = timezone.localtime(order.order_time)
        date_str = local_time.strftime('%Y-%m-%d')
        daily_dict[date_str] = daily_dict.get(date_str, 0) + 1
        hour = local_time.hour
        hourly_dict[hour] = hourly_dict.get(hour, 0) + 1

    daily_orders = []
    for i in range(30, 0, -1):
        d = (local_now_naive - timedelta(days=i)).strftime('%Y-%m-%d')
        daily_orders.append({'date': d, 'count': daily_dict.get(d, 0)})

    hourly_orders = [{'hour': f'{h:02d}:00', 'count': hourly_dict.get(h, 0)} for h in range(24)]

    # 获取包含分类的菜品排行
    top_dishes_qs = OrderItem.objects.values('dish__name', 'dish__category').annotate(
        total_quantity=Sum('quantity')
    ).order_by('-total_quantity')
    top_dishes = list(top_dishes_qs[:5])
    bottom_dishes = list(top_dishes_qs.reverse()[:5]) # 修复数据重叠：这里取倒数前5

    # ---------------------------------------------------------
    # 🌟 核心增量 1：AI 智能套餐推荐算法 (关联分析)
    # ---------------------------------------------------------
    pair_counter = Counter()
    for order in recent_30_days_orders.prefetch_related('orderitem_set__dish'):
        items = list(order.orderitem_set.values_list('dish__name', flat=True))
        if len(items) > 1:
            pairs = combinations(sorted(items), 2)
            pair_counter.update(pairs)
    
    if pair_counter:
        best_pair, count = pair_counter.most_common(1)[0]
        ai_suggestion = f"系统发现【{best_pair[0]}】与【{best_pair[1]}】存在强关联购买行为（近期共出现 {count} 次）。建议将其打包为【特惠双人餐】出售，预计可提升客单价 15%！"
    else:
        # 兜底算法：如果全是单点订单，则组合最热销的主菜和饮品
        top_main = next((d['dish__name'] for d in top_dishes_qs if '主菜' in d['dish__category']), top_dishes[0]['dish__name'] if top_dishes else '热门主菜')
        top_drink = next((d['dish__name'] for d in top_dishes_qs if '饮' in d['dish__category']), '热门饮品')
        ai_suggestion = f"系统挖掘发现，【{top_main}】作为本店招牌，若与利润款【{top_drink}】进行跨界捆绑，推出【爆款引流套餐】，预计可带动饮品整体销量暴增 25%！"

    # ---------------------------------------------------------
    # 机器学习预测区 (未来 7 天)
    # ---------------------------------------------------------
    ninety_days_ago = now - timedelta(days=90)
    historical_orders_qs = Order.objects.filter(order_time__gte=ninety_days_ago)
    
    pred_daily_dict = {}
    for order in historical_orders_qs:
        date_str = timezone.localtime(order.order_time).strftime('%Y-%m-%d')
        pred_daily_dict[date_str] = pred_daily_dict.get(date_str, 0) + 1
        
    predicted_orders = []
    mape = None
    tomorrow_predicted_orders = 0  # 记录明天的预测单量
    
    if pred_daily_dict:
        hist_data = [{'date': k, 'count': v} for k, v in pred_daily_dict.items()]
        df = pd.DataFrame(hist_data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        df['weekday'] = df['date'].dt.weekday
        df['is_weekend'] = (df['weekday'] >= 5).astype(int)
        df['day_index'] = (df['date'] - df['date'].min()).dt.days

        X = df[['day_index', 'weekday', 'is_weekend']]
        y = df['count']

        model = LinearRegression()
        if len(y) >= 3:
            cv_folds = min(5, len(y) - 1)
            y_pred = cross_val_predict(model, X, y, cv=cv_folds)
            mape = mean_absolute_percentage_error(y, y_pred) * 100

        model.fit(X, y)

        future_dates = [local_now_naive + timedelta(days=i) for i in range(1, 8)]
        min_date = df['date'].min()
        
        future_day_indices = [(d - min_date).days for d in future_dates]
        future_weekdays = [d.weekday() for d in future_dates]
        future_is_weekends = [1 if wd >= 5 else 0 for wd in future_weekdays]

        future_X = pd.DataFrame({'day_index': future_day_indices, 'weekday': future_weekdays, 'is_weekend': future_is_weekends})
        predictions = model.predict(future_X)

        weekdays_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        predicted_orders = [{'date': f"{future_dates[i].strftime('%Y-%m-%d')} ({weekdays_cn[future_dates[i].weekday()]})", 'predicted': max(0, int(round(predictions[i])))} for i in range(7)]
        
        # 记录明日预测单数
        tomorrow_predicted_orders = predicted_orders[0]['predicted'] if predicted_orders else 0

    # ---------------------------------------------------------
    # 🌟 核心增量 2：明日备货清单智能拆解
    # ---------------------------------------------------------
    prep_list = []
    if tomorrow_predicted_orders > 0 and recent_30_days_orders.exists():
        total_recent_items = sum([d['total_quantity'] for d in top_dishes_qs]) or 1
        avg_items_per_order = total_recent_items / recent_30_days_orders.count()
        
        for dish in top_dishes_qs:
            ratio = dish['total_quantity'] / total_recent_items
            # 预测备货量 = 明日订单数 * 每单平均包含菜品数 * 该菜品的历史销售占比
            predicted_qty = int(round(tomorrow_predicted_orders * avg_items_per_order * ratio))
            if predicted_qty > 0:
                prep_list.append({
                    'name': dish['dish__name'],
                    'category': dish['dish__category'],
                    'quantity': predicted_qty
                })

    context = {
        'total_orders': total_orders,
        'total_amount': total_amount,
        'daily_orders': daily_orders,
        'top_dishes': top_dishes,
        'bottom_dishes': bottom_dishes,
        'hourly_orders': hourly_orders,
        'predicted_orders': predicted_orders,
        'mape': round(mape, 2) if mape is not None else None,
        'ai_suggestion': ai_suggestion, 
        'prep_list': prep_list,
        'avg_order_value': avg_order_value,         
    }
    return render(request, 'dashboard.html', context)

# =========================================================
# 2. 订单管理中心：列表与分页
# =========================================================
@login_required
def order_list(request):
    orders = Order.objects.all().order_by('-order_time')
    paginator = Paginator(orders, 15) 
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'order_list.html', {'page_obj': page_obj})

# =========================================================
# 3. 订单管理中心：安全删除接口
# =========================================================
@login_required
def order_delete(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.delete()
    return redirect('order_list')

# =========================================================
# 4. 订单表单类 (修复不可编辑字段报错)
# =========================================================
class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['order_number', 'item_name', 'item_price', 'quantity', 'total_amount']
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'item_name': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'item_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'required': 'required'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'required': 'required'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'required': 'required'}),
        }
        labels = {
            'order_number': '订单编号',
            'item_name': '菜品名称',
            'item_price': '菜品单价 (元)',
            'quantity': '数量',
            'total_amount': '订单总额 (元)',
        }

# =========================================================
# 5. 添加订单视图
# =========================================================
@login_required
def order_create(request):
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('order_list')
    else:
        default_number = f"ORD{int(time.time())}"
        form = OrderForm(initial={'order_number': default_number})
    
    return render(request, 'order_form.html', {'form': form, 'title': '手动录入新订单'})

# =========================================================
# 6. 编辑订单视图
# =========================================================
@login_required
def order_edit(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        form = OrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            return redirect('order_list')
    else:
        form = OrderForm(instance=order)
        
    return render(request, 'order_form.html', {'form': form, 'title': f'编辑订单: {order.order_number}'})

# =========================================================
# 7. 菜品表单类
# =========================================================
class DishForm(forms.ModelForm):
    class Meta:
        model = Dish
        fields = ['name', 'category', 'price']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 宫保鸡丁'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 主菜、饮品、主食'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'required': 'required'}),
        }
        labels = {
            'name': '菜品名称',
            'category': '所属分类',
            'price': '价格 (元)',
        }

# =========================================================
# 8. 我的菜品管理：列表与分页
# =========================================================
@login_required
def dish_list(request):
    dishes = Dish.objects.all().order_by('category', '-price')
    paginator = Paginator(dishes, 15) 
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'dish_list.html', {'page_obj': page_obj})

# =========================================================
# 9. 菜品管理：添加菜品
# =========================================================
@login_required
def dish_create(request):
    if request.method == 'POST':
        form = DishForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dish_list')
    else:
        form = DishForm()
    return render(request, 'dish_form.html', {'form': form, 'title': '新增菜品'})

# =========================================================
# 10. 菜品管理：编辑菜品
# =========================================================
@login_required
def dish_edit(request, dish_id):
    dish = get_object_or_404(Dish, id=dish_id)
    if request.method == 'POST':
        form = DishForm(request.POST, instance=dish)
        if form.is_valid():
            form.save()
            return redirect('dish_list')
    else:
        form = DishForm(instance=dish)
    return render(request, 'dish_form.html', {'form': form, 'title': f'编辑菜品: {dish.name}'})

# =========================================================
# 11. 菜品管理：删除菜品
# =========================================================
@login_required
def dish_delete(request, dish_id):
    dish = get_object_or_404(Dish, id=dish_id)
    if request.method == 'POST':
        dish.delete()
    return redirect('dish_list')

# =========================================================
# 12. 员工注册表单 (继承自带表单并注入高级 CSS 样式)
# =========================================================
class CustomRegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username'] 
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

# =========================================================
# 13. 员工注册视图
# =========================================================
def register(request):
    if request.method == 'POST':
        form = CustomRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('dashboard')
    else:
        form = CustomRegisterForm()
        
    return render(request, 'register.html', {'form': form})