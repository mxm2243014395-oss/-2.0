from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from restaurant import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 登录登出
    path('', auth_views.LoginView.as_view(template_name='login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # 🌟 报错就是因为漏掉了下面这一行：注册新员工
    path('register/', views.register, name='register'),
    
    # 大屏
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
    
    # ======== 员工账号管理 ========
    path('users/', views.user_list, name='user_list'),
    path('users/edit/<int:user_id>/', views.user_edit, name='user_edit'),
    path('users/delete/<int:user_id>/', views.user_delete, name='user_delete'),
]