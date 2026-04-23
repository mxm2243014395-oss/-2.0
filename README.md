# 智慧餐厅订单预测与运营监控可视化

## 项目简介 (About)
本项目是一个基于 Django 的智慧餐厅管理系统，围绕“订单数据驱动经营决策”展开，提供运营看板、销量分析、订单预测与备货建议等能力。它解决了传统餐厅在人工统计、经验备货、运营洞察滞后方面的问题，帮助管理者通过可视化和预测模型更高效地进行经营分析与库存决策。

## 技术栈 (Tech Stack)
- **后端框架**: Django（MTV 架构）
- **编程语言**: Python
- **数据库**: MySQL（通过 Django ORM 访问）
- **前端技术**: Django Templates + JavaScript + ECharts
- **数据分析/预测**:
  - `pandas`
  - `numpy`
  - `statsmodels`（ARIMA / Holt-Winters）
  - `pmdarima`（auto_arima）
  - `scikit-learn`（线性回归、交叉验证、MAPE 评估）
- **其他能力**: Django 内置认证（Auth）、分页（Paginator）、缓存（LocMemCache）

## 目录结构 (Folder Structure)
```text
-2.0/
├── manage.py                       # Django 命令入口（runserver、migrate 等）
├── settings.py                     # 全局配置（数据库、缓存、模板、静态资源）
├── urls.py                         # 根路由配置
├── wsgi.py                         # WSGI 入口（生产部署常用）
├── README.md
├── fix_order_time.py               # 数据处理/修复脚本
├── restaurant/                     # 核心业务 App
│   ├── apps.py
│   ├── models.py                   # 数据模型（Dish / Order / OrderItem）
│   ├── views.py                    # 业务逻辑（看板、预测、CRUD、权限）
│   ├── migrations/                 # 数据库迁移文件
│   └── management/
│       └── commands/
│           └── sync_items.py       # 自定义导数命令（CSV 同步）
├── templates/                      # 页面模板（登录、看板、订单/菜品/员工管理）
│   ├── dashboard.html
│   ├── login.html
│   ├── register.html
│   ├── order_list.html
│   ├── order_form.html
│   ├── dish_list.html
│   ├── dish_form.html
│   ├── user_list.html
│   └── user_form.html
└── -2.0data/                       # 原始/清洗/模拟数据文件
    ├── raw_order_data_2022-2023.xlsx
    ├── cleaned_order_data.csv
    └── mock_orders_10k.csv
```

## 核心功能模块 (Key Features)
- **运营可视化大屏**: 展示总订单、营业额、客单价、趋势图、热力分布、支付方式占比等核心指标。
- **订单预测分析**: 基于历史订单构建时间序列模型，对未来订单量进行预测并展示误差评估（MAPE）。
- **智能备货建议**: 结合历史销量占比、当前库存与安全库存阈值，自动生成次日建议采购清单。
- **业务数据管理**: 提供订单、菜品、员工账号的增删改查与条件筛选能力。
- **权限与安全访问**: 基于 Django Auth 的登录认证与角色分流（管理员/员工）控制。

## 快速开始 (Getting Started)

### 环境依赖要求
- Python 3.9+（推荐 3.10 或 3.11）
- MySQL 8.x（或兼容版本）
- pip（Python 包管理器）

### 安装依赖
> 当前仓库未提供 `requirements.txt`，可先手动安装核心依赖：

```bash
pip install django pymysql pandas numpy statsmodels pmdarima scikit-learn
```

### 数据库准备
1. 在 MySQL 中创建数据库：

```sql
CREATE DATABASE smart_restaurant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. 根据本机环境修改 `settings.py` 中的数据库账号/密码。

3. 执行迁移：

```bash
python manage.py migrate
```

### 本地启动运行
```bash
python manage.py runserver
```

启动后访问：`http://127.0.0.1:8000/`

## 部署/打包指令 (Build/Deploy)
当前仓库未包含 Docker、CI/CD 或 Nginx 配置文件，暂无统一打包脚本。可按 Django 常规方式部署：

```bash
python manage.py collectstatic
```

并使用 WSGI 服务加载 `wsgi.py` 进行生产部署（如 Gunicorn/uWSGI/Waitress），再按需在服务器侧配置 Nginx 反向代理。
