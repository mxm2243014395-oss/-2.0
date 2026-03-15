from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from restaurant import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 1. 🌟 把网址根目录 '/' 直接设为登录页！
    # redirect_authenticated_user=True：已登录用户访问网址时，直接放行到大屏
    path('', auth_views.LoginView.as_view(template_name='login.html', redirect_authenticated_user=True), name='login'),
    
    # 退出登录的路由
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # 2. 🌟 把原来的大屏主页移到 '/dashboard/' 路径下
    path('dashboard/', views.dashboard, name='dashboard'), 
    
    # ======== 订单管理中心 ========
    path('orders/', views.order_list, name='order_list'),
    path('orders/add/', views.order_create, name='order_create'),
    path('orders/edit/<int:order_id>/', views.order_edit, name='order_edit'),
    path('orders/delete/<int:order_id>/', views.order_delete, name='order_delete'),
    
    # ======== 我的菜品管理 ========
    path('dishes/', views.dish_list, name='dish_list'),
    path('dishes/add/', views.dish_create, name='dish_create'),
    path('dishes/edit/<int:dish_id>/', views.dish_edit, name='dish_edit'),
    path('dishes/delete/<int:dish_id>/', views.dish_delete, name='dish_delete'),
]