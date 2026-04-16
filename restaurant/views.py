from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta
from .models import Order, Dish
from django.db.models import Sum
from django.core.paginator import Paginator  # 导入分页器
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
# 1. 运营监控大屏视图
#    保留函数，但暂时不执行 OrderItem / Dish 相关逻辑
# =========================================================
@login_required
def dashboard(request):
    total_orders = Order.objects.count()
    total_amount = Order.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
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

    # 这里先不执行 OrderItem / Dish 的统计、推荐、预测相关逻辑
    top_dishes = []
    bottom_dishes = []
    predicted_orders = []
    mape = None
    ai_suggestion = ''
    prep_list = []
    predicted_revenue = 0
    actual_vs_pred_data = []
    top_predicted_dishes = []

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
        'predicted_revenue': predicted_revenue,
        'actual_vs_pred_data': actual_vs_pred_data,
        'top_predicted_dishes': top_predicted_dishes,
    }
    return render(request, 'dashboard.html', context)

# =========================================================
# 2. 订单管理中心：列表、分页与多条件联合搜索
# =========================================================
@login_required
def order_list(request):
    # 1. 获取所有订单基础查询集
    orders = Order.objects.all().order_by('-order_time')
    
    # 2. 获取前端传来的搜索参数
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    dish_name = request.GET.get('dish_name', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')

    # 3. 动态拼接筛选条件 (Django ORM 神器)
    if start_date:
        orders = orders.filter(order_time__date__gte=start_date) # 大于等于开始日期
    if end_date:
        orders = orders.filter(order_time__date__lte=end_date)   # 小于等于结束日期
    if dish_name:
        orders = orders.filter(item_name__icontains=dish_name)   # 菜名模糊包含查询
    if min_price:
        orders = orders.filter(total_amount__gte=min_price)      # 金额大于等于
    if max_price:
        orders = orders.filter(total_amount__lte=max_price)      # 金额小于等于

    # 4. 设置分页器
    paginator = Paginator(orders, 15) 
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # 5. 组装查询字符串，传递给前端分页器，防止翻页时丢失搜索条件
    query_params = request.GET.copy()
    if 'page' in query_params:
        del query_params['page']
    query_string = query_params.urlencode()
    
    context = {
        'page_obj': page_obj,
        'query_string': query_string, # 将参数串传给页面
    }
    return render(request, 'order_list.html', context)

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
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'required': 'required', 'placeholder': '例如: 宫保鸡丁'}),
        }
        labels = {
            'name': '菜品名称',
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

# =========================================================
# 14. 员工账号管理：列表展示
# =========================================================
@login_required
def user_list(request):
    # 获取所有用户，按注册时间倒序排列
    users = User.objects.all().order_by('-date_joined')
    paginator = Paginator(users, 15) 
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'user_list.html', {'page_obj': page_obj})

# =========================================================
# 15. 员工账号管理：编辑表单 (分配权限、停用账号)
# =========================================================
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
        # 🌟 核心防越权 1：提取视图层传进来的“当前登录用户 (current_user)”
        self.current_user = kwargs.pop('current_user', None)
        super().__init__(*args, **kwargs)
        
        # 🌟 核心防越权 2：如果当前登录的不是店长，强制锁死“店长权限”复选框！
        if self.current_user and not self.current_user.is_superuser:
            self.fields['is_superuser'].disabled = True
            # 给普通员工一个温馨提示，防止他们觉得是系统卡了点不动
            self.fields['is_superuser'].label = '授予店长权限 (⚠️ 权限不足：仅现任店长可勾选此项)'

@login_required
def user_edit(request, user_id):
    edit_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        # 🌟 把当前发请求的人 (request.user) 塞进表单里做权限判断
        form = UserEditForm(request.POST, instance=edit_user, current_user=request.user)
        if form.is_valid():
            form.save()
            return redirect('user_list')
    else:
        # 🌟 GET 请求展示页面时，同样塞入当前用户
        form = UserEditForm(instance=edit_user, current_user=request.user)
        
    return render(request, 'user_form.html', {'form': form, 'title': f'编辑员工权限: {edit_user.username}'})

# =========================================================
# 16. 员工账号管理：安全删除
# =========================================================
@login_required
def user_delete(request, user_id):
    delete_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        # 🌟 核心防越权 3：删除接口的终极拦截
        if not request.user.is_superuser:
            pass # 如果不是店长发起的删除请求，静默忽略，不执行删除
        elif delete_user == request.user:
            pass # 店长也不能把自己删了（否则系统就没店长了）
        else:
            delete_user.delete()
            
    return redirect('user_list')