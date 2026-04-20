from datetime import datetime, time as dt_time, timedelta
import time
import traceback

import numpy as np
import pandas as pd
from django import forms
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, ExtractHour
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.timezone import make_aware
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error

from .models import Dish, Order
from django.db.models import F

def _parse_month_param(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m')
    except ValueError:
        return None


def _parse_day_param(value):
    if not value:
        return None
    normalized = value.strip().replace('/', '-')
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(normalized.split(' ')[0], '%Y-%m-%d')
    except ValueError:
        return None


def _aware_start_of_day(dt_value):
    if timezone.is_naive(dt_value):
        return make_aware(datetime.combine(dt_value.date(), dt_time.min))
    return dt_value.replace(hour=0, minute=0, second=0, microsecond=0)


def _aware_end_of_day(dt_value):
    if timezone.is_naive(dt_value):
        return make_aware(datetime.combine(dt_value.date(), dt_time.max))
    return dt_value.replace(hour=23, minute=59, second=59, microsecond=999999)


def _cache_count(queryset, cache_key):
    total_count = cache.get(cache_key)
    if total_count is None:
        total_count = queryset.count()
        cache.set(cache_key, total_count, 300)
    return total_count


def _query_signature(params_dict):
    items = sorted((k, v) for k, v in params_dict.items() if v not in ('', None))
    return '&'.join(f'{k}={v}' for k, v in items)


def get_tomorrow_predicted_orders():
    orders = list(Order.objects.order_by('order_time').values_list('order_time', flat=True))
    if len(orders) < 2:
        return 0.0, None, None, None

    first_day = timezone.localtime(orders[0]).date()
    day_to_total = {}
    for dt in orders:
        d = timezone.localtime(dt).date()
        day_to_total[d] = day_to_total.get(d, 0) + 1

    sorted_days = sorted(day_to_total.keys())
    if len(sorted_days) < 2:
        return 0.0, None, None, None

    x = np.array([(day - first_day).days for day in sorted_days], dtype=float).reshape(-1, 1)
    y = np.array([day_to_total[day] for day in sorted_days], dtype=float)

    if len(x) < 2:
        return 0.0, None, None, None

    model = LinearRegression()
    model.fit(x, y)
    y_pred = model.predict(x)
    try:
        mape = float(mean_absolute_percentage_error(y, y_pred))
    except Exception:
        mape = None

    tomorrow_offset = (timezone.localtime(orders[-1]).date() - first_day).days + 1
    tomorrow_predicted_orders = float(max(0.0, model.predict(np.array([[tomorrow_offset]], dtype=float))[0]))
    actual_vs_pred_data = [
        {
            'date': day.strftime('%Y-%m-%d'),
            'actual': int(day_to_total[day]),
            'predicted': float(y_pred[i]),
        }
        for i, day in enumerate(sorted_days)
    ]
    predicted_revenue = 0
    return tomorrow_predicted_orders, mape, actual_vs_pred_data, predicted_revenue


@login_required
def dashboard(request):
    total_orders = Order.objects.count()
    total_amount = Order.objects.aggregate(total=Sum('total_amount'))['total'] or 0
    avg_order_value = total_amount / total_orders if total_orders > 0 else 0

    total_amount_wan = total_amount / 10000 if total_amount else 0
    avg_order_value = total_amount / total_orders if total_orders > 0 else 0

    # 1. 动态时间锚点 (解决测试数据时间断层)
    latest_order = Order.objects.order_by('-order_time').first()
    anchor_date = timezone.localtime(latest_order.order_time).date() if latest_order else timezone.now().date()
    
    month_param = request.GET.get('month')
    day_param = request.GET.get('day')
    if day_param:
        target_date = datetime.strptime(day_param, '%Y-%m-%d').date()
    elif month_param:
        target_date = datetime.strptime(month_param + '-01', '%Y-%m-%d').date()
    else:
        target_date = anchor_date

    # 2. 基础图表统计
    trend_start_date = target_date - timedelta(days=29)
    aware_trend_start = make_aware(datetime.combine(trend_start_date, dt_time.min))
    aware_target_end = make_aware(datetime.combine(target_date, dt_time.max))
    aware_target_start = make_aware(datetime.combine(target_date, dt_time.min))

    # 30天趋势 (变量名叫 daily_orders)
    trend_dts = Order.objects.filter(order_time__gte=aware_trend_start, order_time__lte=aware_target_end).values_list('order_time', flat=True)
    daily_map = {}
    for dt in trend_dts:
        d_str = timezone.localtime(dt).strftime('%Y-%m-%d')
        daily_map[d_str] = daily_map.get(d_str, 0) + 1
    daily_orders = [{'date': (trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 'count': daily_map.get((trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 0)} for i in range(30)]

    # 24小时分布
    hourly_dts = Order.objects.filter(order_time__gte=aware_target_start, order_time__lte=aware_target_end).values_list('order_time', flat=True)
    hourly_map = {}
    for dt in hourly_dts:
        h = timezone.localtime(dt).hour
        hourly_map[h] = hourly_map.get(h, 0) + 1
    hourly_orders = [{'hour': f'{h:02d}:00', 'count': hourly_map.get(h, 0)} for h in range(24)]

    # 滞销/热销菜品
    all_dishes = list(Dish.objects.values('name'))
    dish_sales_map = {item['item_name']: int(item['total_sales'] or 0) for item in Order.objects.filter(order_time__gte=aware_trend_start, order_time__lte=aware_target_end).values('item_name').annotate(total_sales=Sum('quantity')) if item['item_name']}
    bottom_dishes = sorted([{'name': d['name'], 'value': dish_sales_map.get(d['name'], 0)} for d in all_dishes], key=lambda x: (x['value'], x['name']))[:5]
    top_dishes = sorted([{'name': d['name'], 'value': dish_sales_map.get(d['name'], 0)} for d in all_dishes], key=lambda x: (-x['value'], x['name']))[:5]

    # =========================================================
    # 🌟 核心板块：机器学习预测 (未来 7 天)
    # =========================================================
    ninety_days_ago = target_date - timedelta(days=90)
    aware_90_start = make_aware(datetime.combine(ninety_days_ago, dt_time.min))
    
    historical_dts = Order.objects.filter(order_time__gte=aware_90_start, order_time__lte=aware_target_end).values_list('order_time', flat=True)
    
    pred_daily_dict = {}
    for dt in historical_dts:
        date_str = timezone.localtime(dt).strftime('%Y-%m-%d')
        pred_daily_dict[date_str] = pred_daily_dict.get(date_str, 0) + 1
        
    predicted_orders = []
    mape = None
    tomorrow_predicted_orders = 0
    prep_list = []
    
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

        future_dates = [target_date + timedelta(days=i) for i in range(1, 8)]
        min_date = df['date'].min()
        
        future_day_indices = [(pd.Timestamp(d) - min_date).days for d in future_dates]
        future_weekdays = [d.weekday() for d in future_dates]
        future_is_weekends = [1 if wd >= 5 else 0 for wd in future_weekdays]

        future_X = pd.DataFrame({'day_index': future_day_indices, 'weekday': future_weekdays, 'is_weekend': future_is_weekends})
        predictions = model.predict(future_X)

        weekdays_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        predicted_orders = [{'date': f"{future_dates[i].strftime('%Y-%m-%d')} ({weekdays_cn[future_dates[i].weekday()]})", 'predicted': max(0, int(round(predictions[i])))} for i in range(7)]
        
        tomorrow_predicted_orders = predicted_orders[0]['predicted'] if predicted_orders else 0

    # 智能备货单拆解
    if tomorrow_predicted_orders > 0:
        total_recent_sales = sum(dish_sales_map.values()) or 1
        avg_items_per_order = total_recent_sales / (len(trend_dts) or 1)
        
        dish_info_map = {d['name']: d['category'] for d in Dish.objects.values('name', 'category')}
        
        for dish_name, sales in dish_sales_map.items():
            ratio = sales / total_recent_sales
            predicted_qty = int(round(tomorrow_predicted_orders * avg_items_per_order * ratio))
            if predicted_qty > 0:
                prep_list.append({
                    'name': dish_name,
                    'category': dish_info_map.get(dish_name, '未知'),
                    'quantity': predicted_qty
                })
        prep_list = sorted(prep_list, key=lambda x: x['quantity'], reverse=True)

    # 纯净的 context，绝无 daily_trend！
    context = {
        'total_orders': total_orders,
        'total_amount': total_amount,
        'total_amount_wan': total_amount_wan,
        'daily_orders': daily_orders,
        'top_dishes': top_dishes,
        'bottom_dishes': bottom_dishes,
        'hourly_orders': hourly_orders,
        'predicted_orders': predicted_orders,
        'mape': round(mape, 2) if mape is not None else None,
        'prep_list': prep_list,
        'avg_order_value': avg_order_value,
        'predicted_revenue': tomorrow_predicted_orders * avg_order_value,
    }
    return render(request, 'dashboard.html', context)


@login_required
def order_list(request):
    orders_queryset = (
        Order.objects.only(
            'order_number',
            'order_time',
            'item_name',
            'category',
            'quantity',
            'total_amount',
            'payment_method',
            'time_of_sale',
        )
        .select_related()
        .order_by('-order_time')
    )

    start_date = (request.GET.get('start_date') or '').strip()
    end_date = (request.GET.get('end_date') or '').strip()
    dish_name = (request.GET.get('dish_name') or '').strip()
    min_price = (request.GET.get('min_price') or '').strip()
    max_price = (request.GET.get('max_price') or '').strip()

    start_dt = _parse_day_param(start_date)
    end_dt = _parse_day_param(end_date)

    if start_dt:
        orders_queryset = orders_queryset.filter(order_time__gte=_aware_start_of_day(start_dt))
    if end_dt:
        orders_queryset = orders_queryset.filter(order_time__lte=_aware_end_of_day(end_dt))
    if dish_name:
        orders_queryset = orders_queryset.filter(item_name__icontains=dish_name)
    if min_price:
        orders_queryset = orders_queryset.filter(total_amount__gte=min_price)
    if max_price:
        orders_queryset = orders_queryset.filter(total_amount__lte=max_price)

    query_signature = _query_signature({
        'start_date': start_date,
        'end_date': end_date,
        'dish_name': dish_name,
        'min_price': min_price,
        'max_price': max_price,
    })
    cache_key = f'order_list_total_count:{query_signature or "all"}'
    total_count = _cache_count(orders_queryset, cache_key)

    paginator = Paginator(orders_queryset, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    context = {
        'page_obj': page_obj,
        'query_string': query_string,
        'total_count': total_count,
    }
    return render(request, 'order_list.html', context)


def _dashboard_range_from_params(month_param, day_param):
    latest_order = Order.objects.order_by('-order_time').only('order_time').first()

    def _month_range(anchor_date):
        month_start = anchor_date.replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)
        trend_start = make_aware(datetime.combine(month_start, dt_time.min))
        trend_end = make_aware(datetime.combine(month_end, dt_time.min)) - timedelta(microseconds=1)
        return trend_start, trend_end

    def _latest_month_and_day():
        if not latest_order:
            return None, None
        latest_local = timezone.localtime(latest_order.order_time)
        trend_start, trend_end = _month_range(latest_local.date())
        heatmap_day = make_aware(datetime.combine(latest_local.date(), dt_time.min))
        return trend_start, trend_end, heatmap_day

    if day_param:
        day_dt = _parse_day_param(day_param)
        if day_dt:
            selected_day = timezone.localtime(day_dt).date()
            trend_start, trend_end = _month_range(selected_day)
            heatmap_day = make_aware(datetime.combine(selected_day, dt_time.min))
            return trend_start, trend_end, heatmap_day, None

    if month_param:
        month_dt = _parse_month_param(month_param)
        if month_dt:
            selected_month = month_dt.date().replace(day=1)
            trend_start, trend_end = _month_range(selected_month)
            if latest_order:
                heatmap_day = make_aware(datetime.combine(timezone.localtime(latest_order.order_time).date(), dt_time.min))
                return trend_start, trend_end, heatmap_day, None

    # 优先展示“最后一个有数据的月份”与“最后一天”
    if latest_order:
        latest_local = timezone.localtime(latest_order.order_time)
        trend_start, trend_end = _month_range(latest_local.date())
        heatmap_day = make_aware(datetime.combine(latest_local.date(), dt_time.min))

        # 如果最近一个月没有数据，向前滚动查找最近一个有数据的月份
        if not Order.objects.filter(order_time__gte=trend_start, order_time__lte=trend_end).exists():
            probe_date = latest_local.date().replace(day=1)
            for _ in range(36):
                if probe_date.month == 1:
                    probe_date = probe_date.replace(year=probe_date.year - 1, month=12)
                else:
                    probe_date = probe_date.replace(month=probe_date.month - 1)
                probe_start, probe_end = _month_range(probe_date)
                if Order.objects.filter(order_time__gte=probe_start, order_time__lte=probe_end).exists():
                    trend_start, trend_end = probe_start, probe_end
                    break

        # 如果最后一天没数据，向前找最近一天有数据的日期
        if not Order.objects.filter(order_time__gte=_aware_start_of_day(heatmap_day), order_time__lte=_aware_end_of_day(heatmap_day)).exists():
            probe_day = latest_local.date()
            for _ in range(90):
                probe_day -= timedelta(days=1)
                probe_start = make_aware(datetime.combine(probe_day, dt_time.min))
                probe_end = make_aware(datetime.combine(probe_day, dt_time.max))
                if Order.objects.filter(order_time__gte=probe_start, order_time__lte=probe_end).exists():
                    heatmap_day = probe_start
                    break

        return trend_start, trend_end, heatmap_day, None

    now = timezone.now()
    return now - timedelta(days=29), now, now, None


def dashboard_data_api(request):
    try:
        month_param = request.GET.get('month')
        day_param = request.GET.get('day')
        
        # 1. 获取最新订单日期作为锚点，保证默认能看到数据
        latest_order = Order.objects.order_by('-order_time').first()
        if not latest_order:
            # 如果数据库一条数据都没有的兜底
            return JsonResponse({'daily_trend': [], 'hourly_distribution': [], 'category_revenue': [], 'time_of_sale_orders': [], 'payment_method_orders': [], 'top_dishes': []})

        anchor_date = timezone.localtime(latest_order.order_time).date()

        if day_param:
            target_date = datetime.strptime(day_param, '%Y-%m-%d').date()
        elif month_param:
            target_date = datetime.strptime(month_param + '-01', '%Y-%m-%d').date()
        else:
            target_date = anchor_date

        # 2. 核心数据统计 ======
        trend_start_date = target_date - timedelta(days=29)
        aware_trend_start = make_aware(datetime.combine(trend_start_date, dt_time.min))
        aware_target_end = make_aware(datetime.combine(target_date, dt_time.max))
        aware_target_start = make_aware(datetime.combine(target_date, dt_time.min))

        # A. 30天趋势 (绕开 TruncDate，使用超快只读内存统计)
        # 只取时间字段，绝不实例化 Order 对象，速度极快
        trend_dts = Order.objects.filter(
            order_time__gte=aware_trend_start, 
            order_time__lte=aware_target_end
        ).values_list('order_time', flat=True)
        
        daily_map = {}
        for dt in trend_dts:
            d_str = timezone.localtime(dt).strftime('%Y-%m-%d')
            daily_map[d_str] = daily_map.get(d_str, 0) + 1
            
        daily_trend = []
        for i in range(30):
            d_str = (trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_trend.append({'date': d_str, 'count': daily_map.get(d_str, 0)})

        # B. 24小时分布 (绕开 ExtractHour)
        hourly_dts = Order.objects.filter(
            order_time__gte=aware_target_start, 
            order_time__lte=aware_target_end
        ).values_list('order_time', flat=True)
        
        hourly_map = {}
        for dt in hourly_dts:
            h = timezone.localtime(dt).hour
            hourly_map[h] = hourly_map.get(h, 0) + 1
            
        hourly_distribution = [{'count': hourly_map.get(h, 0)} for h in range(24)]

        # C. 菜品分类营收 (全局)
        cat_qs = Order.objects.values('category').annotate(value=Sum('total_amount'))
        category_revenue = [{'name': item['category'] or '未知', 'value': float(item['value'] or 0)} for item in cat_qs if item['category']]

        # D. 售卖时段 (全局)
        time_qs = Order.objects.values('time_of_sale').annotate(value=Count('id'))
        time_of_sale_orders = [{'name': item['time_of_sale'] or '未知', 'value': item['value']} for item in time_qs if item['time_of_sale']]

        # E. 支付方式 (全局)
        pay_qs = Order.objects.values('payment_method').annotate(value=Count('id'))
        payment_method_orders = [{'name': item['payment_method'] or '未知', 'value': item['value']} for item in pay_qs if item['payment_method']]

        # F. 销量 TOP 5 (全局)
        dish_qs = Order.objects.values('item_name').annotate(value=Sum('quantity')).order_by('-value')[:5]
        top_dishes = [{'name': item['item_name'] or '未知', 'value': int(item['value'] or 0)} for item in dish_qs if item['item_name']]

        return JsonResponse({
            'daily_trend': daily_trend,
            'hourly_distribution': hourly_distribution,
            'category_revenue': category_revenue,
            'time_of_sale_orders': time_of_sale_orders,
            'payment_method_orders': payment_method_orders,
            'top_dishes': top_dishes
        })

    except Exception as e:
        print("❌ API 内部崩溃详细日志:")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def order_delete(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.delete()
    return redirect('order_list')


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['order_number', 'item_name', 'category', 'quantity', 'total_amount', 'payment_method', 'time_of_sale']
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'item_name': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'required': 'required'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'required': 'required'}),
            'payment_method': forms.TextInput(attrs={'class': 'form-control'}),
            'time_of_sale': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'order_number': '订单编号',
            'item_name': '菜品名称',
            'category': '菜品分类',
            'quantity': '数量',
            'total_amount': '订单总额 (元)',
            'payment_method': '支付方式',
            'time_of_sale': '售卖时段',
        }


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


class DishForm(forms.ModelForm):
    class Meta:
        model = Dish
        fields = ['name', 'category', 'price', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 宫保鸡丁'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 快餐 / 饮品'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'required': 'required', 'step': '0.01', 'placeholder': '例如: 28.00'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': '请输入菜品简介'}),
        }
        labels = {
            'name': '菜品名称',
            'category': '菜品分类',
            'price': '菜品单价',
            'description': '菜品简介',
        }


@login_required
def dish_list(request):
    # 1. 基础查询集和分页器
    dishes_queryset = Dish.objects.only('name', 'category', 'price', 'current_stock', 'safety_stock', 'description').order_by('category', '-price')
    cache_key = 'dish_list_total_count:all'
    total_count = _cache_count(dishes_queryset, cache_key)

    paginator = Paginator(dishes_queryset, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    # 2. 获取全局销量聚合数据和 AI 预测数据
    sales_rows = Order.objects.values('item_name').annotate(total_sales=Sum('quantity'))
    dish_sales_map = {row['item_name']: int(row['total_sales'] or 0) for row in sales_rows if row['item_name']}
    total_sales_all = sum(dish_sales_map.values())
    tomorrow_predicted_orders, _, _, _ = get_tomorrow_predicted_orders()

    # =======================================================
    # 🌟 极致优化点 1：使用 F() 表达式在数据库层直接秒查缺货菜品
    # =======================================================
    low_stock_qs = Dish.objects.filter(current_stock__lte=F('safety_stock')).order_by('current_stock')
    
    low_stock_dishes = []
    # 只需要遍历查出来的少数缺货菜品，拼接上历史销量即可
    for dish in low_stock_qs:
        low_stock_dishes.append({
            'name': dish.name,
            'current_stock': dish.current_stock,
            'safety_stock': dish.safety_stock,
            'sold': dish_sales_map.get(dish.name, 0),
        })

    # =======================================================
    # 🌟 优化点 2：单独计算 AI 采购单
    # =======================================================
    purchase_list = []
    for dish in dishes_queryset:
        sold = dish_sales_map.get(dish.name, 0)
        
        # 计算预估消耗
        if total_sales_all > 0 and tomorrow_predicted_orders > 0:
            expected_consumption = tomorrow_predicted_orders * (sold / total_sales_all)
        else:
            expected_consumption = 0

        # 核心进销存公式：建议采购量 = 预估消耗 + 安全库存 - 现有库存
        suggested_purchase = expected_consumption + dish.safety_stock - dish.current_stock
        
        if suggested_purchase > 0:
            purchase_list.append({
                'name': dish.name,
                'current_stock': dish.current_stock,
                'safety_stock': dish.safety_stock,
                'history_sales': sold,
                'expected_consumption': round(expected_consumption, 1), # 保留1位小数更美观
                'suggested_purchase': int(round(suggested_purchase)),   # 采购量通常需要整数
            })

    # 按建议采购量倒序排列，优先展示最急需进货的菜品
    purchase_list = sorted(purchase_list, key=lambda x: (x['suggested_purchase'], x['current_stock'], x['name']), reverse=True)

    return render(request, 'dish_list.html', {
        'page_obj': page_obj,
        'query_string': query_string,
        'total_count': total_count,
        'low_stock_dishes': low_stock_dishes,
        'purchase_list': purchase_list,
    })

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


@login_required
def dish_delete(request, dish_id):
    dish = get_object_or_404(Dish, id=dish_id)
    if request.method == 'POST':
        dish.delete()
    return redirect('dish_list')


class CustomRegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


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


@login_required
def user_list(request):
    users = User.objects.all().order_by('-date_joined')
    paginator = Paginator(users, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'user_list.html', {'page_obj': page_obj})


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'is_superuser', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'is_superuser': forms.CheckboxInput(attrs={'style': 'width: 20px; height: 20px; cursor: pointer;'}),
            'is_active': forms.CheckboxInput(attrs={'style': 'width: 20px; height: 20px; cursor: pointer;'}),
        }
        labels = {
            'username': '员工登录账号',
            'is_superuser': '授予店长权限 (可查看运营大屏及所有数据)',
            'is_active': '允许登录 (取消勾选即为停用该员工账号)',
        }

    def __init__(self, *args, **kwargs):
        self.current_user = kwargs.pop('current_user', None)
        super().__init__(*args, **kwargs)
        if self.current_user and not self.current_user.is_superuser:
            self.fields['is_superuser'].disabled = True
            self.fields['is_superuser'].label = '授予店长权限 (⚠️ 权限不足：仅现任店长可勾选此项)'


@login_required
def user_edit(request, user_id):
    edit_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=edit_user, current_user=request.user)
        if form.is_valid():
            form.save()
            return redirect('user_list')
    else:
        form = UserEditForm(instance=edit_user, current_user=request.user)

    return render(request, 'user_form.html', {'form': form, 'title': f'编辑员工权限: {edit_user.username}'})


@login_required
def user_delete(request, user_id):
    delete_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        if not request.user.is_superuser:
            pass
        elif delete_user == request.user:
            pass
        else:
            delete_user.delete()

    return redirect('user_list')
