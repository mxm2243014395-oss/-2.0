from django.contrib import admin
from django.urls import path
from restaurant import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
]