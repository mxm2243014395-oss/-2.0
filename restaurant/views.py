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
from django.db.models import Count, Sum, F
from django.db.models.functions import TruncDate, ExtractHour
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.timezone import make_aware
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error

from .models import Dish, Order

# 顶部新增引入
from statsmodels.tsa.holtwinters import ExponentialSmoothing
import warnings
from statsmodels.tools.sm_exceptions import ConvergenceWarning
warnings.simplefilter('ignore', ConvergenceWarning) # 忽略底层计算的冗余警告

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
    # 1. 基础统计
    total_orders = Order.objects.count()
    total_amount = Order.objects.aggregate(total=Sum('total_amount'))['total'] or 0
    total_amount_wan = total_amount / 10000 if total_amount else 0
    avg_order_value = total_amount / total_orders if total_orders > 0 else 0

    # 2. 🌟 确定时间基准：真正的【此时此刻】
    now = timezone.now()
    today = now.date()
    
    # 获取筛选参数
    month_param = request.GET.get('month')
    day_param = request.GET.get('day')
    if day_param:
        target_date = datetime.strptime(day_param, '%Y-%m-%d').date()
    elif month_param:
        target_date = datetime.strptime(month_param + '-01', '%Y-%m-%d').date()
    else:
        target_date = today

    # 3. 基础图表统计 (30天趋势)
    trend_start_date = target_date - timedelta(days=29)
    aware_trend_start = make_aware(datetime.combine(trend_start_date, dt_time.min))
    aware_target_end = make_aware(datetime.combine(target_date, dt_time.max))
    
    trend_orders_qs = Order.objects.filter(order_time__gte=aware_trend_start, order_time__lte=aware_target_end)
    trend_dts = trend_orders_qs.values_list('order_time', flat=True)
    
    daily_map = {}
    for dt in trend_dts:
        d_str = timezone.localtime(dt).strftime('%Y-%m-%d')
        daily_map[d_str] = daily_map.get(d_str, 0) + 1
    daily_orders = [{'date': (trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 'count': daily_map.get((trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 0)} for i in range(30)]

    # 4. 24小时分布
    aware_target_start = make_aware(datetime.combine(target_date, dt_time.min))
    hourly_dts = Order.objects.filter(order_time__gte=aware_target_start, order_time__lte=aware_target_end).values_list('order_time', flat=True)
    hourly_map = {}
    for dt in hourly_dts:
        h = timezone.localtime(dt).hour
        hourly_map[h] = hourly_map.get(h, 0) + 1
    hourly_orders = [{'hour': f'{h:02d}:00', 'count': hourly_map.get(h, 0)} for h in range(24)]

   # 5. 销量分析 (用于补货权重)
    all_dishes = list(Dish.objects.values('name', 'category', 'current_stock', 'safety_stock'))
    
    # 🚨 核心修复 1：去掉时间限制，获取全库历史总销量，与“菜品管理”完全对齐
    dish_sales_qs = Order.objects.values('item_name').annotate(total_sales=Sum('quantity'))
    dish_sales_map = {item['item_name']: int(item['total_sales'] or 0) for item in dish_sales_qs if item['item_name']}
    
    bottom_dishes = sorted([{'name': d['name'], 'value': dish_sales_map.get(d['name'], 0)} for d in all_dishes], key=lambda x: (x['value'], x['name']))[:5]
    top_dishes = sorted([{'name': d['name'], 'value': dish_sales_map.get(d['name'], 0)} for d in all_dishes], key=lambda x: (-x['value'], x['name']))[:5]

  # =========================================================
    # 🌟 核心板块：时间序列预测 (Holt-Winters 指数平滑)
    # =========================================================
    historical_all = Order.objects.values('order_time')
    pred_daily_dict = {}
    for item in historical_all:
        d_str = timezone.localtime(item['order_time']).strftime('%Y-%m-%d')
        pred_daily_dict[d_str] = pred_daily_dict.get(d_str, 0) + 1
        
    predicted_orders = []
    actual_vs_pred_data = []
    mape = None
    tomorrow_predicted_orders = 0
    purchase_list = []
    
    # 🌟 时序模型通常需要更长的数据来捕捉周期，这里设为至少需要 7 天数据
    if pred_daily_dict and len(pred_daily_dict) >= 7:
        # 1. 构建标准的时间序列 DataFrame
        df = pd.DataFrame([{'date': k, 'count': v} for k, v in pred_daily_dict.items()])
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.sort_index(inplace=True)
        
        # 🌟 关键：餐饮数据可能某天没营业（缺数据），时序模型要求时间必须连续
        # 因此生成连续的日期索引，并将缺失的日期销量填充为 0
        idx = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
        df = df.reindex(idx, fill_value=0)
        
        y = df['count'].astype(float)

        # 2. 构建 Holt-Winters 时序模型
        # 餐饮业通常具有 7 天的强周期性 (seasonal_periods=7)
        # 使用加法模型 (add) 处理趋势和季节性
        try:
            # 如果数据量大于两周，启用季节性；否则只用简单趋势平滑
            seasonal_opt = 'add' if len(y) >= 14 else None
            periods_opt = 7 if len(y) >= 14 else None
            
            model = ExponentialSmoothing(
                y, 
                trend='add', 
                seasonal=seasonal_opt, 
                seasonal_periods=periods_opt, 
                initialization_method="estimated"
            )
            fit_model = model.fit()

            # 3. 提取历史拟合数据 (用于图表对比和计算误差)
            historical_fitted = fit_model.fittedvalues
            
            # 计算全量样本的 MAPE
            # 过滤掉真实值为0的天数以防止除以0的数学错误
            valid_idx = y > 0
            if valid_idx.any():
                mape = mean_absolute_percentage_error(y[valid_idx], historical_fitted[valid_idx]) * 100
            else:
                mape = 0

            # 组装最近 14 天的历史对比数据供前端展示
            display_days = min(14, len(y))
            for i in range(len(y) - display_days, len(y)):
                actual_vs_pred_data.append({
                    'date': y.index[i].strftime('%Y-%m-%d'), 
                    'actual': int(y.iloc[i]),
                    'predicted': max(0, int(round(historical_fitted.iloc[i])))
                })

            # 4. 🌟 预测未来 7 天
            forecast_values = fit_model.forecast(7)
            weekdays_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            
            for i in range(7):
                f_date = today + timedelta(days=i+1)
                f_weekday = f_date.weekday()
                p_count = forecast_values.iloc[i]
                
                predicted_orders.append({
                    'date': f"{f_date.strftime('%Y-%m-%d')} ({weekdays_cn[f_weekday]})", 
                    'predicted': max(0, int(round(p_count)))
                })
            
            tomorrow_predicted_orders = predicted_orders[0]['predicted']
            
        except Exception as e:
            print(f"时序模型拟合失败，退回初始状态: {e}")
            tomorrow_predicted_orders = 0



    # =======================================================
    # 🌟 核心修复 2：完全恢复与菜品管理一模一样的进销存公式
    # =======================================================
    purchase_list = []
    if tomorrow_predicted_orders > 0:
        total_sales_all = sum(dish_sales_map.values()) or 1
        
        all_dishes_obj = Dish.objects.all()
        for dish in all_dishes_obj:
            sold = dish_sales_map.get(dish.name, 0)
            
            # 计算预估消耗 = 明日预测单量 * (该菜品历史销量 / 历史总销量)
            expected_consumption = tomorrow_predicted_orders * (sold / total_sales_all)
            
            # 恢复正确的进销存科学公式！
            suggested_purchase = expected_consumption + dish.safety_stock - dish.current_stock

            # 只要建议采购量大于0，就必须买
            if suggested_purchase > 0:
                purchase_list.append({
                    'name': dish.name,
                    'category': dish.category,
                    'current_stock': dish.current_stock,
                    'safety_stock': dish.safety_stock,
                    'history_sales': sold,
                    'expected_consumption': round(expected_consumption, 1),
                    'suggested_purchase': int(round(suggested_purchase))
                })
        
        # 按照缺货严重程度（即需要买多少）进行排序
        purchase_list = sorted(purchase_list, key=lambda x: (x['suggested_purchase'], x['current_stock'], x['name']), reverse=True)

    context = {
        'total_orders': total_orders,
        'total_amount': total_amount,
        'total_amount_wan': total_amount_wan,
        'daily_orders': daily_orders,
        'top_dishes': top_dishes,
        'bottom_dishes': bottom_dishes,
        'hourly_orders': hourly_orders,
        'actual_vs_pred_data': actual_vs_pred_data,
        'predicted_orders': predicted_orders,
        'mape': round(mape, 2) if mape is not None else None,
        'purchase_list': purchase_list,
        'avg_order_value': avg_order_value,
        'predicted_revenue': tomorrow_predicted_orders * avg_order_value,
        'now': timezone.now(), 
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

    if latest_order:
        latest_local = timezone.localtime(latest_order.order_time)
        trend_start, trend_end = _month_range(latest_local.date())
        heatmap_day = make_aware(datetime.combine(latest_local.date(), dt_time.min))

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
        
        latest_order = Order.objects.order_by('-order_time').first()
        if not latest_order:
            return JsonResponse({'daily_trend': [], 'hourly_distribution': [], 'category_revenue': [], 'time_of_sale_orders': [], 'payment_method_orders': [], 'top_dishes': []})

        anchor_date = timezone.localtime(latest_order.order_time).date()

        if day_param:
            target_date = datetime.strptime(day_param, '%Y-%m-%d').date()
        elif month_param:
            target_date = datetime.strptime(month_param + '-01', '%Y-%m-%d').date()
        else:
            target_date = anchor_date

        trend_start_date = target_date - timedelta(days=29)
        aware_trend_start = make_aware(datetime.combine(trend_start_date, dt_time.min))
        aware_target_end = make_aware(datetime.combine(target_date, dt_time.max))
        aware_target_start = make_aware(datetime.combine(target_date, dt_time.min))

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

        hourly_dts = Order.objects.filter(
            order_time__gte=aware_target_start, 
            order_time__lte=aware_target_end
        ).values_list('order_time', flat=True)
        
        hourly_map = {}
        for dt in hourly_dts:
            h = timezone.localtime(dt).hour
            hourly_map[h] = hourly_map.get(h, 0) + 1
            
        hourly_distribution = [{'count': hourly_map.get(h, 0)} for h in range(24)]

        cat_qs = Order.objects.values('category').annotate(value=Sum('total_amount'))
        category_revenue = [{'name': item['category'] or '未知', 'value': float(item['value'] or 0)} for item in cat_qs if item['category']]

        time_qs = Order.objects.values('time_of_sale').annotate(value=Count('id'))
        time_of_sale_orders = [{'name': item['time_of_sale'] or '未知', 'value': item['value']} for item in time_qs if item['time_of_sale']]

        pay_qs = Order.objects.values('payment_method').annotate(value=Count('id'))
        payment_method_orders = [{'name': item['payment_method'] or '未知', 'value': item['value']} for item in pay_qs if item['payment_method']]

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
        fields = ['name', 'category', 'price', 'current_stock', 'safety_stock', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 宫保鸡丁'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 快餐 / 饮品'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'required': 'required', 'step': '0.01', 'placeholder': '例如: 28.00'}),
            'current_stock': forms.NumberInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '当前店内剩余份数'}),
            'safety_stock': forms.NumberInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '低于此值时将在管理台预警'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': '请输入菜品简介'}),
        }
        labels = {
            'name': '菜品名称',
            'category': '菜品分类',
            'price': '菜品单价 (元)',
            'current_stock': '当前库存 (份)',
            'safety_stock': '安全预警阈值 (份)',
            'description': '菜品简介',
        }


@login_required
def dish_list(request):
    dishes_queryset = Dish.objects.only('name', 'category', 'price', 'current_stock', 'safety_stock', 'description').order_by('category', '-price')
    cache_key = 'dish_list_total_count:all'
    total_count = _cache_count(dishes_queryset, cache_key)

    paginator = Paginator(dishes_queryset, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    sales_rows = Order.objects.values('item_name').annotate(total_sales=Sum('quantity'))
    dish_sales_map = {row['item_name']: int(row['total_sales'] or 0) for row in sales_rows if row['item_name']}
    total_sales_all = sum(dish_sales_map.values())
    tomorrow_predicted_orders, _, _, _ = get_tomorrow_predicted_orders()

    low_stock_qs = Dish.objects.filter(current_stock__lte=F('safety_stock')).order_by('current_stock')
    
    low_stock_dishes = []
    for dish in low_stock_qs:
        low_stock_dishes.append({
            'name': dish.name,
            'current_stock': dish.current_stock,
            'safety_stock': dish.safety_stock,
            'sold': dish_sales_map.get(dish.name, 0),
        })

    purchase_list = []
    for dish in dishes_queryset:
        sold = dish_sales_map.get(dish.name, 0)
        
        if total_sales_all > 0 and tomorrow_predicted_orders > 0:
            expected_consumption = tomorrow_predicted_orders * (sold / total_sales_all)
        else:
            expected_consumption = 0

        suggested_purchase = expected_consumption + dish.safety_stock - dish.current_stock
        
        if suggested_purchase > 0:
            purchase_list.append({
                'name': dish.name,
                'current_stock': dish.current_stock,
                'safety_stock': dish.safety_stock,
                'history_sales': sold,
                'expected_consumption': round(expected_consumption, 1),
                'suggested_purchase': int(round(suggested_purchase)),
            })

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
    # 后端强制拦截：如果不是店长（超级管理员），直接重定向并报错
    if not request.user.is_superuser:
        messages.error(request, "对不起，您没有删除菜品的权限！")
        return redirect('/dish_list/')
    
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
    # 新增拦截逻辑：非店长访问直接重定向回大屏
    if not request.user.is_superuser:
        return redirect('dashboard') 

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