import os
import sys
import django
import pandas as pd
import random
import time
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

# --- 1. Django Environment Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventory.models import Product

# --- 2. Configuration ---
MONTHS_TO_GENERATE = 6

def get_valid_fg_products():
    """
    Fetches the actual Product objects for Finished Goods (FG).
    """
    products = list(Product.objects.filter(nature='FG'))
    if not products:
        print("❌ Error: No 'FG' (Finished Goods) found in the database.")
        sys.exit(1)
    return products

def generate_wide_format_forecast():
    """
    Generates a Matrix (Wide Format) dataset.
    """
    # [关键修改] 强制重置随机数种子，使用当前时间戳
    random.seed(datetime.now().timestamp())

    products = get_valid_fg_products()

    today = date.today()
    start_month = today.replace(day=1) + relativedelta(months=1)

    date_columns = []
    for i in range(MONTHS_TO_GENERATE):
        current_month = start_month + relativedelta(months=i)
        date_columns.append(current_month.strftime('%Y-%m-%d'))

    data = []
    print(f"Generating forecast for months: {date_columns}")

    for product in products:
        row = {
            'SKU': product.sku,
            'Product Name': product.description,
        }

        # [逻辑优化] 让每个SKU也有点“个性”，不仅仅是纯随机
        # 为每个产品分配一个“基础销量”，避免所有产品看起来都一样
        base_volume = random.randint(10, 100)

        for month_col in date_columns:
            # 30% chance of 0 demand
            if random.random() < 0.3:
                qty = 0
            else:
                # 波动范围在 base_volume 的 50% ~ 150% 之间
                variance = random.uniform(0.5, 1.5)
                qty = int(base_volume * variance) * 10

            row[month_col] = qty

        data.append(row)

    return data, date_columns

def save_to_excel(data, date_cols, filename="sales_forecast_sample.xlsx"):
    if not data: return
    df = pd.DataFrame(data)
    cols = ['SKU', 'Product Name'] + date_cols
    df = df[cols]

    try:
        file_path = os.path.join(current_dir, filename)
        # 尝试写入，如果文件被打开会报错
        df.to_excel(file_path, index=False)
        print(f"\n✅ File Generated Successfully: {file_path}")
        print(f"   - Rows: {len(data)}")
    except PermissionError:
        print(f"\n❌ Error: Cannot write to '{filename}'.")
        print("   👉 Please CLOSE the Excel file and try again.")
    except Exception as e:
        print(f"❌ Failed to save Excel file: {e}")

if __name__ == "__main__":
    forecast_data, cols = generate_wide_format_forecast()
    save_to_excel(forecast_data, cols)
