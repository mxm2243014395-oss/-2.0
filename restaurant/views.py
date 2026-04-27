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
from django.db.models import Sum, Count, Avg
from .models import Dish, Order
from restaurant.models import Order, Dish, OrderItem
# 顶部新增引入
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
# 引入自动寻优算法库
from pmdarima import auto_arima
import warnings
from statsmodels.tools.sm_exceptions import ConvergenceWarning
warnings.simplefilter('ignore', ConvergenceWarning) # 忽略底层计算的冗余警告

from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages

from django.db.models import Sum, Count, Avg, F

# 定义一个检查是否为店长（超级用户）的函数
def is_manager(user):
    return user.is_superuser

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

def _build_order_forecast_payload():
    """
    统一订单预测口径：
    - 以数据库最后一天为序列终点，补齐到真实今天，再给出未来 7 天预测
    - 明日预测取“真实明天”的第一天预测值
    """
    empty_payload = {
        'tomorrow_predicted_orders': 0,
        'mape': None,
        'actual_vs_pred_data': [],
        'predicted_orders': [],
    }

    orders = list(Order.objects.order_by('order_time').values_list('order_time', flat=True))
    if len(orders) < 14:
        return empty_payload

    day_to_total = {}
    for dt in orders:
        d = timezone.localtime(dt).date()
        day_to_total[d] = day_to_total.get(d, 0) + 1

    df = pd.DataFrame([{'date': k, 'count': v} for k, v in day_to_total.items()])
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    df.sort_index(inplace=True)

    idx = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
    df = df.reindex(idx, fill_value=0)
    y = df['count'].astype(float)
    if len(y) < 14:
        return empty_payload

    try:
        # ==========================================
        # 🌟 步骤 1：数据集切分 (80/20 Time-Series Split)
        # ==========================================
        train_size = int(len(y) * 0.8)
        y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]

        mape_hw = None
        mape_naive = None

        # ==========================================
        # 🌟 步骤 2：模型评估 (Out-of-Sample 盲测)
        # ==========================================
        if len(y_train) >= 14 and len(y_test) > 0:
            model_hw = ExponentialSmoothing(
                y_train,
                trend='add',
                seasonal='add',
                seasonal_periods=7,
                initialization_method="estimated"
            )
            fit_hw = model_hw.fit()

            pred_hw = fit_hw.forecast(len(y_test))
            valid_mask_hw = y_test > 0
            if valid_mask_hw.any():
                mape_hw = float(mean_absolute_percentage_error(y_test[valid_mask_hw], pred_hw[valid_mask_hw]) * 100)

            naive_preds = []
            full_series = pd.concat([y_train, y_test])
            for i in range(len(y_test)):
                current_idx = train_size + i
                naive_val = full_series.iloc[current_idx - 7]
                naive_preds.append(naive_val)
            pred_naive = pd.Series(naive_preds, index=y_test.index)

            valid_mask_naive = y_test > 0
            if valid_mask_naive.any():
                mape_naive = float(mean_absolute_percentage_error(y_test[valid_mask_naive], pred_naive[valid_mask_naive]) * 100)

        # ==========================================
        # 🌟 步骤 3：业务应用 (全量拟合与跨时空外推)
        # ==========================================
        final_model = ExponentialSmoothing(
            y,
            trend='add',
            seasonal='add',
            seasonal_periods=7,
            initialization_method="estimated"
        )
        final_fit = final_model.fit()
        historical_fitted = final_fit.fittedvalues
        mape = mape_hw

        actual_vs_pred_data = []
        display_days = min(14, len(y))
        for i in range(len(y) - display_days, len(y)):
            actual_vs_pred_data.append({
                'date': y.index[i].strftime('%Y-%m-%d'),
                'actual': int(y.iloc[i]),
                'predicted': max(0, int(round(historical_fitted.iloc[i]))),
            })

        last_db_date = y.index.max().date()
        real_today = timezone.now().date()
        days_gap = max(0, (real_today - last_db_date).days)
        total_forecast_steps = days_gap + 7

        forecast_all = final_fit.forecast(total_forecast_steps)
        weekdays_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

        predicted_orders = []
        for i in range(days_gap, total_forecast_steps):
            f_date = last_db_date + timedelta(days=i + 1)
            p_count = max(0, int(round(forecast_all.iloc[i])))
            predicted_orders.append({
                'date': f"{f_date.strftime('%Y-%m-%d')} ({weekdays_cn[f_date.weekday()]})",
                'predicted': p_count,
            })

        tomorrow_predicted_orders = predicted_orders[0]['predicted'] if predicted_orders else 0

        return {
            'tomorrow_predicted_orders': tomorrow_predicted_orders,
            'mape': mape,
            'mape_naive': mape_naive,
            'actual_vs_pred_data': actual_vs_pred_data,
            'predicted_orders': predicted_orders,
        }
    except Exception as e:
        print(f"Holt-Winters 统一预测计算失败: {e}")
        return empty_payload

def get_tomorrow_predicted_orders():
    forecast_payload = _build_order_forecast_payload()
    tomorrow_predicted_orders = float(forecast_payload['tomorrow_predicted_orders'])
    mape = forecast_payload['mape']
    actual_vs_pred_data = forecast_payload['actual_vs_pred_data']
    predicted_revenue = 0
    return tomorrow_predicted_orders, mape, actual_vs_pred_data, predicted_revenue

@login_required
def dashboard(request):
    # =========================================================
    # 🌟 1. 权限拦截与基础统计
    # =========================================================
    if not request.user.is_superuser:
        return redirect('dish_list')

    # 基础宏观数据
    total_orders = Order.objects.count()
    total_amount_agg = Order.objects.aggregate(total=Sum('total_amount'))['total'] or 0
    total_amount = float(total_amount_agg)
    total_amount_wan = total_amount / 10000
    avg_order_value = total_amount / total_orders if total_orders > 0 else 0

    # =========================================================
    # 🌟 2. 时间基准逻辑：自动锁定数据库有数据的最后一天
    # =========================================================
    today = timezone.now().date()
    latest_order = Order.objects.order_by('-order_time').first()
    
    if latest_order:
        # 自动获取数据库中最新的一笔订单日期作为默认展示日
        default_date = timezone.localtime(latest_order.order_time).date()
    else:
        default_date = today
    
    # 处理筛选参数
    day_param = request.GET.get('day')
    month_param = request.GET.get('month')
    
    if day_param:
        target_date = datetime.strptime(day_param, '%Y-%m-%d').date()
    elif month_param:
        target_date = datetime.strptime(month_param + '-01', '%Y-%m-%d').date()
    else:
        target_date = default_date

    target_date_str = target_date.strftime('%Y-%m-%d')

    # 定义时间边界 (30天滑动窗口)
    trend_start_date = target_date - timedelta(days=29)
    aware_trend_start = make_aware(datetime.combine(trend_start_date, dt_time.min))
    aware_target_start = make_aware(datetime.combine(target_date, dt_time.min)) 
    aware_target_end = make_aware(datetime.combine(target_date, dt_time.max))

    # =========================================================
    # 🌟 3. 核心统计：选定日营业额与 30 天趋势
    # =========================================================
    
    # 选定日当天的总营业额
    daily_rev_agg = Order.objects.filter(
        order_time__gte=aware_target_start, 
        order_time__lte=aware_target_end
    ).aggregate(total=Sum('total_amount'))
    daily_revenue = float(daily_rev_agg['total'] or 0)

    # 30天订单量趋势
    trend_orders_qs = Order.objects.filter(order_time__gte=aware_trend_start, order_time__lte=aware_target_end)
    trend_dts = trend_orders_qs.values_list('order_time', flat=True)
    
    daily_map = {}
    for dt in trend_dts:
        d_str = timezone.localtime(dt).strftime('%Y-%m-%d')
        daily_map[d_str] = daily_map.get(d_str, 0) + 1
    
    daily_orders = [
        {
            'date': (trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 
            'count': daily_map.get((trend_start_date + timedelta(days=i)).strftime('%Y-%m-%d'), 0)
        } for i in range(30)
    ]

    # 24小时客流分布
    hourly_dts = Order.objects.filter(
        order_time__gte=aware_target_start, 
        order_time__lte=aware_target_end
    ).values_list('order_time', flat=True)
    
    hourly_map = {}
    for dt in hourly_dts:
        h = timezone.localtime(dt).hour
        hourly_map[h] = hourly_map.get(h, 0) + 1
    hourly_orders = [{'hour': f'{h:02d}:00', 'count': hourly_map.get(h, 0)} for h in range(24)]

    # =========================================================
    # 🌟 4. 销量分析：通过 OrderItem 联表查询
    # =========================================================
    all_dishes_info = list(Dish.objects.values('id', 'name', 'category', 'current_stock', 'safety_stock'))
    
    # 基于 OrderItem 统计真实销量 (跨表到 Dish 获取名称)
    dish_sales_qs = OrderItem.objects.values('dish__name').annotate(total_sales=Sum('quantity'))
    dish_sales_map = {
        item['dish__name']: int(item['total_sales'] or 0) 
        for item in dish_sales_qs if item['dish__name']
    }
    
    # 构建排行榜
    sales_ranking_data = [
        {'name': d['name'], 'value': dish_sales_map.get(d['name'], 0)} 
        for d in all_dishes_info
    ]
    bottom_dishes = sorted(sales_ranking_data, key=lambda x: (x['value'], x['name']))[:5]
    top_dishes = sorted(sales_ranking_data, key=lambda x: (-x['value'], x['name']))[:5]

    # =========================================================
    # 🌟 5. 时间序列预测（统一口径）
    # =========================================================
    forecast_payload = _build_order_forecast_payload()
    predicted_orders = forecast_payload['predicted_orders']
    actual_vs_pred_data = forecast_payload['actual_vs_pred_data']
    mape = forecast_payload['mape']
    tomorrow_predicted_orders = forecast_payload['tomorrow_predicted_orders']

    # =========================================================
    # 🌟 6. 进销存补货逻辑
    # =========================================================
    purchase_list = []
    if tomorrow_predicted_orders > 0:
        total_sales_all = sum(dish_sales_map.values()) or 1
        
        for dish in Dish.objects.all():
            sold = dish_sales_map.get(dish.name, 0)
            # 计算该菜品在全量销售中的权重，据此分配明日预估消耗
            expected_consumption = tomorrow_predicted_orders * (sold / total_sales_all)
            suggested_purchase = expected_consumption + dish.safety_stock - dish.current_stock

            if suggested_purchase > 0:
                purchase_list.append({
                    'name': dish.name,
                    'category': dish.category,
                    'current_stock': dish.current_stock,
                    'safety_stock': dish.safety_stock,
                    'expected_consumption': round(expected_consumption, 1),
                    'suggested_purchase': int(round(suggested_purchase))
                })
        
        purchase_list = sorted(purchase_list, key=lambda x: x['suggested_purchase'], reverse=True)

    # =========================================================
    # 🌟 7. 返回安全 Context
    # =========================================================
    context = {
        'total_orders': int(total_orders),
        'total_amount': float(total_amount),
        'total_amount_wan': float(total_amount_wan),
        'avg_order_value': float(avg_order_value),
        'daily_revenue': float(daily_revenue),
        'target_date_str': target_date_str,
        'daily_orders': daily_orders,
        'top_dishes': top_dishes,
        'bottom_dishes': bottom_dishes,
        'hourly_orders': hourly_orders,
        'actual_vs_pred_data': actual_vs_pred_data,
        'predicted_orders': predicted_orders,
        'mape_hw': round(forecast_payload.get('mape', 0), 2) if forecast_payload.get('mape') is not None else None,
        'mape_naive': round(forecast_payload.get('mape_naive', 0), 2) if forecast_payload.get('mape_naive') is not None else None,
        'purchase_list': purchase_list,
        'predicted_revenue': float(tomorrow_predicted_orders * avg_order_value),
        'now': timezone.now(), 
    }
    return render(request, 'dashboard.html', context)


@login_required
def order_list(request):
    # 🌟 修改 1：移除旧的 only()，加入 prefetch_related 进行跨表预加载
    orders_queryset = (
        Order.objects.prefetch_related('items__dish')
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
        # 🌟 修改 2：通过 items(外键) -> dish(菜品表) -> name(字段) 进行联表搜索，并去重
        orders_queryset = orders_queryset.filter(items__dish__name__icontains=dish_name).distinct()
        
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

        # 1. 计算 API 请求的该天营业额 (针对主表)
        daily_revenue_agg = Order.objects.filter(
            order_time__gte=aware_target_start, 
            order_time__lte=aware_target_end
        ).aggregate(total=Sum('total_amount'))
        daily_revenue = float(daily_revenue_agg['total'] or 0)

        # 2. 订单趋势 (针对主表)
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

        # 3. 24小时客流 (针对主表)
        hourly_dts = Order.objects.filter(
            order_time__gte=aware_target_start, 
            order_time__lte=aware_target_end
        ).values_list('order_time', flat=True)
        
        hourly_map = {}
        for dt in hourly_dts:
            h = timezone.localtime(dt).hour
            hourly_map[h] = hourly_map.get(h, 0) + 1
            
        hourly_distribution = [{'count': hourly_map.get(h, 0)} for h in range(24)]

        # ==========================================
        # 🌟 核心修复区：基于 OrderItem 的关联查询
        # ==========================================

        # 4. 菜品分类营收占比 (通过 OrderItem 关联 Dish，计算 数量*单价)
        cat_qs = OrderItem.objects.values('dish__category').annotate(
            value=Sum(F('quantity') * F('price_at_purchase'))
        )
        category_revenue = [{'name': item['dish__category'] or '未知', 'value': float(item['value'] or 0)} for item in cat_qs if item['dish__category']]

        # 5. 销量前五的菜品 (通过 OrderItem 关联 Dish 获取名称)
        dish_qs = OrderItem.objects.values('dish__name').annotate(
            value=Sum('quantity')
        ).order_by('-value')[:5]
        top_dishes = [{'name': item['dish__name'] or '未知', 'value': int(item['value'] or 0)} for item in dish_qs if item['dish__name']]

        # ==========================================

        # 6. 售卖时段与支付方式 (针对主表)
        time_qs = Order.objects.values('time_of_sale').annotate(value=Count('id'))
        time_of_sale_orders = [{'name': item['time_of_sale'] or '未知', 'value': item['value']} for item in time_qs if item['time_of_sale']]

        pay_qs = Order.objects.values('payment_method').annotate(value=Count('id'))
        payment_method_orders = [{'name': item['payment_method'] or '未知', 'value': item['value']} for item in pay_qs if item['payment_method']]

        return JsonResponse({
            'daily_revenue': daily_revenue,
            'daily_trend': daily_trend,
            'hourly_distribution': hourly_distribution,
            'category_revenue': category_revenue,
            'time_of_sale_orders': time_of_sale_orders,
            'payment_method_orders': payment_method_orders,
            'top_dishes': top_dishes
        })

    except Exception as e:
        import traceback
        print("❌ API 内部崩溃详细日志:")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def order_delete(request, order_id):
    # 硬性拦截：如果不是店长，直接重定向并报错
    if not request.user.is_superuser:
        messages.error(request, "【权限拒绝】只有店长可以执行删除操作！")
        return redirect('order_list')
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.delete()
    return redirect('order_list')


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        # 删除了失效的菜品字段，仅保留订单的宏观字段
        fields = ['order_number', 'total_amount', 'payment_method', 'time_of_sale']
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control', 'required': 'required'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'required': 'required'}),
            'payment_method': forms.TextInput(attrs={'class': 'form-control'}),
            'time_of_sale': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'order_number': '订单编号',
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
    # 1. 基础查询
    dishes_queryset = Dish.objects.only('name', 'category', 'price', 'current_stock', 'safety_stock', 'description').order_by('category', '-price')
    cache_key = 'dish_list_total_count:all'
    total_count = _cache_count(dishes_queryset, cache_key)

    paginator = Paginator(dishes_queryset, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()

    # 2. 🌟 核心修复：聚合查询使用了 dish__name，字典取值也必须匹配
    sales_rows = OrderItem.objects.values('dish__name').annotate(total_sales=Sum('quantity'))
    
    # 修正点：将 row['item_name'] 修改为 row['dish__name']
    dish_sales_map = {
        row['dish__name']: int(row['total_sales'] or 0) 
        for row in sales_rows if row['dish__name']
    }
    
    total_sales_all = sum(dish_sales_map.values())
    
    # 获取预测订单数 (假设 get_tomorrow_predicted_orders 已在外部定义)
    try:
        tomorrow_predicted_orders, _, _, _ = get_tomorrow_predicted_orders()
    except Exception as e:
        print(f"预测模型获取失败: {e}")
        tomorrow_predicted_orders = 0

    # 3. 低库存预警逻辑
    low_stock_qs = Dish.objects.filter(current_stock__lte=F('safety_stock')).order_by('current_stock')
    
    low_stock_dishes = []
    for dish in low_stock_qs:
        low_stock_dishes.append({
            'name': dish.name,
            'current_stock': dish.current_stock,
            'safety_stock': dish.safety_stock,
            'sold': dish_sales_map.get(dish.name, 0),
        })

    # 4. 进销存科学补货建议
    purchase_list = []
    for dish in dishes_queryset:
        sold = dish_sales_map.get(dish.name, 0)
        
        # 计算该菜品在全量销售中的比例，进而推算明日预估消耗
        if total_sales_all > 0 and tomorrow_predicted_orders > 0:
            expected_consumption = tomorrow_predicted_orders * (sold / total_sales_all)
        else:
            expected_consumption = 0

        # 补货公式：预估消耗 + 安全库存 - 当前库存
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

    # 按建议补货量从高到低排序
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
            auth_login(request, user) # 自动登录
            
            # ==========================================
            # 🌟 新增：注册并自动登录后的跳转分发
            # ==========================================
            if user.is_superuser:
                return redirect('dashboard')
            else:
                return redirect('dish_list')
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