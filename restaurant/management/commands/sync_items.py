import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from restaurant.models import Order, Dish, OrderItem


class Command(BaseCommand):
    help = '从 CSV 覆盖导入订单数据到 smart_restaurant 数据库'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            dest='csv_path',
            default=str(Path(settings.BASE_DIR).parent / '-2.0data' / 'mock_orders_10k.csv'),
            help='CSV 文件路径'
        )

    def _pick(self, row, *candidates, default=''):
        for key in candidates:
            if key in row and row[key] is not None and str(row[key]).strip() != '':
                return str(row[key]).strip()
        return default

    def _parse_decimal(self, value, default=Decimal('0')):
        text = str(value).strip()
        if not text:
            return default
        text = text.replace(',', '')
        text = re.sub(r'[元￥\s]', '', text)
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return default

    def _parse_int(self, value, default=0):
        text = str(value).strip()
        if not text:
            return default
        text = re.sub(r'[^0-9-]', '', text)
        try:
            return int(text)
        except ValueError:
            return default

    def _parse_datetime(self, value):
        text = str(value).strip()
        if not text:
            return timezone.now()

        patterns = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d %H:%M',
            '%Y/%m/%d',
            '%Y.%m.%d %H:%M:%S',
            '%Y.%m.%d %H:%M',
            '%Y.%m.%d',
        ]
        for pattern in patterns:
            try:
                dt = datetime.strptime(text, pattern)
                return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
            except ValueError:
                continue

        normalized = text.replace('年', '-').replace('月', '-').replace('日', ' ').strip()
        normalized = normalized.replace('时', ':').replace('分', ':').replace('秒', '')
        try:
            dt = datetime.fromisoformat(normalized)
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except ValueError:
            return timezone.now()

    def _table_exists(self, table_name):
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        return table_name in tables

    def _safe_truncate(self, table_name):
        if self._table_exists(table_name):
            with connection.cursor() as cursor:
                cursor.execute(f'TRUNCATE TABLE `{table_name}`')

    @transaction.atomic
    def handle(self, *args, **options):
        csv_path = Path(options['csv_path'])
        if not csv_path.exists():
            self.stdout.write(self.style.ERROR(f'CSV 文件不存在: {csv_path}'))
            return

        # 先尽量使用 TRUNCATE 清空旧数据，避免旧库数据残留
        for table_name in ['restaurant_orderitem', 'restaurant_dish', 'restaurant_order']:
            try:
                self._safe_truncate(table_name)
            except Exception:
                # 如果 TRUNCATE 因外键或权限失败，退回到 ORM 删除
                pass

        # 兜底：确保旧数据被删除
        try:
            OrderItem.objects.all().delete()
        except Exception:
            pass
        try:
            Dish.objects.all().delete()
        except Exception:
            pass
        try:
            Order.objects.all().delete()
        except Exception:
            pass

        with csv_path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                self.stdout.write(self.style.ERROR('CSV 文件没有表头，无法导入'))
                return

            fieldnames = reader.fieldnames
            self.stdout.write(self.style.NOTICE(f'识别到 CSV 列名: {", ".join(fieldnames)}'))

            dish_cache = {}
            orders_to_create = []
            dishes_to_create = []

            for index, row in enumerate(reader, start=1):
                order_id = self._pick(row, '订单ID', '订单编号', 'order_id', 'order_number', default='')
                if order_id:
                    order_number = f'CSV{order_id}' if not str(order_id).startswith('CSV') else str(order_id)
                else:
                    order_number = f'CSV{index:06d}'

                dish_name = self._pick(row, '菜品名称', '商品名称', 'item_name', 'dish_name', 'name', default='未知菜品')
                dish_category = self._pick(row, '菜品分类', '分类', 'category', 'dish_category', default='未知')
                quantity = self._parse_int(self._pick(row, '数量', 'qty', 'quantity', default='1'), default=1)
                total_amount = self._parse_decimal(self._pick(row, '交易总额(元)', '交易总额', '总金额', 'total_amount', 'amount', default='0'))
                payment_method = self._pick(row, '支付方式', 'payment_method', '支付类型', default='其他/现金')
                time_of_sale = self._pick(row, '售卖时段', 'time_of_sale', '时段', default='未知')
                order_time = self._parse_datetime(self._pick(row, '日期', '下单时间', 'order_time', '时间', default=''))

                if dish_name not in dish_cache:
                    dishes_to_create.append(Dish(name=dish_name))
                    dish_cache[dish_name] = True

                orders_to_create.append(
                    Order(
                        order_number=order_number,
                        order_time=order_time,
                        item_name=dish_name,
                        category=dish_category,
                        quantity=quantity,
                        total_amount=total_amount,
                        payment_method=payment_method,
                        time_of_sale=time_of_sale,
                    )
                )

        Dish.objects.bulk_create(dishes_to_create, ignore_conflicts=True)
        Order.objects.bulk_create(orders_to_create, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f'成功覆盖导入 {len(orders_to_create)} 条订单数据到 smart_restaurant'))