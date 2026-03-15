from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
from .models import Order, OrderItem
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate, ExtractHour
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor

from sklearn.model_selection import cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error

def _daily_aggregate(start_date, end_date):
    """
    按天汇总订单数和营收，兼容MySQL
    """
    return Order.objects.filter(order_time__gte=start_date, order_time__lte=end_date).annotate(
        date=TruncDate('order_time')
    ).values('date').annotate(count=Count('id'), revenue=Sum('total_amount')).order_by('date')

def dashboard(request):
    # 总订单数
    total_orders = Order.objects.count()

    # 总订单金额
    total_amount = Order.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # 最近30天每日订单量趋势
    thirty_days_ago = timezone.now() - timedelta(days=30)
    daily_orders_qs = _daily_aggregate(thirty_days_ago, timezone.now())
    daily_orders = [{'date': str(item['date']), 'count': item['count']} for item in daily_orders_qs]

    # 热销菜品TOP 5
    top_dishes_qs = OrderItem.objects.values('dish__name').annotate(
        total_quantity=Sum('quantity')
    ).order_by('-total_quantity')[:5]
    top_dishes = list(top_dishes_qs)

    # 滞销菜品Bottom 10
    bottom_dishes_qs = OrderItem.objects.values('dish__name').annotate(
        total_quantity=Sum('quantity')
    ).order_by('total_quantity')[:10]
    bottom_dishes = list(bottom_dishes_qs)

    # 24小时订单热力图
    hourly_orders_qs = Order.objects.annotate(hour=ExtractHour('order_time')).values('hour').annotate(count=Count('id')).order_by('hour')
    hourly_orders = [{'hour': item['hour'], 'count': item['count']} for item in hourly_orders_qs]

    # 订单预测逻辑
    ninety_days_ago = timezone.now() - timedelta(days=90)
    historical_orders = Order.objects.filter(order_time__gte=ninety_days_ago).annotate(
        date=TruncDate('order_time')
    ).values('date').annotate(count=Count('id')).order_by('date')

    predicted_orders = []
    mape = None
    if historical_orders:
        df = pd.DataFrame(list(historical_orders))
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)  # 移除时区，使其tz-naive
        df['weekday'] = df['date'].dt.weekday
        df['is_weekend'] = (df['weekday'] >= 5).astype(int)  # 周六日为1
        df['day_index'] = (df['date'] - df['date'].min()).dt.days

        X = df[['day_index', 'weekday', 'is_weekend']]
        y = df['count']

        # 计算预测准确度 (MAPE) 使用交叉验证
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        if len(y) >= 3:
            cv_folds = min(5, len(y) - 1)
            y_pred = cross_val_predict(model, X, y, cv=cv_folds)
            mape = mean_absolute_percentage_error(y, y_pred) * 100
        else:
            mape = None  # 样本不足，无法计算

        # 重新训练模型用于预测
        model.fit(X, y)

        # 预测未来7天
        future_dates = [timezone.now() + timedelta(days=i) for i in range(1, 8)]
        future_dates_tz_naive = [d.replace(tzinfo=None) for d in future_dates]  # 移除时区
        min_date = df['date'].min()
        future_day_indices = [(future_dates_tz_naive[0] - min_date).days + i for i in range(7)]
        future_weekdays = [d.weekday() for d in future_dates_tz_naive]
        future_is_weekends = [1 if wd >= 5 else 0 for wd in future_weekdays]

        future_X = pd.DataFrame({
            'day_index': future_day_indices,
            'weekday': future_weekdays,
            'is_weekend': future_is_weekends
        })
        predictions = model.predict(future_X)

        predicted_orders = [
            {'date': future_dates[i].strftime('%Y-%m-%d'), 'predicted': int(round(predictions[i]))}
            for i in range(7)
        ]

    context = {
        'total_orders': total_orders,
        'total_amount': total_amount,
        'daily_orders': daily_orders,
        'top_dishes': top_dishes,
        'bottom_dishes': bottom_dishes,
        'hourly_orders': hourly_orders,
        'predicted_orders': predicted_orders,
        'mape': round(mape, 2) if mape is not None else None,
    }
    return render(request, 'dashboard.html', context)