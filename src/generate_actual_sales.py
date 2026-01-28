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
    products = list(Product.objects.filter(nature='FG'))
    if not products:
        print("❌ Error: No 'FG' (Finished Goods) found.")
        sys.exit(1)
    return products

def generate_actual_sales_data():
    """
    Generates a Matrix (Wide Format) dataset for ACTUAL ORDERS.
    """
    # [关键修改] 强制重置随机数种子，并在Forecast的基础上偏移一点时间，确保绝对随机
    random.seed(datetime.now().timestamp() + 12345)

    products = get_valid_fg_products()

    today = date.today()
    start_month = today.replace(day=1) + relativedelta(months=1)

    date_columns = []
    for i in range(MONTHS_TO_GENERATE):
        current_month = start_month + relativedelta(months=i)
        date_columns.append(current_month.strftime('%Y-%m-%d'))

    data = []
    print(f"Generating Actual Sales (Orders) for months: {date_columns}")

    for product in products:
        row = {
            'SKU': product.sku,
            'Product Name': product.description,
        }

        for month_col in date_columns:
            chance = random.random()

            # [逻辑优化] 增加随机波动范围
            if chance < 0.4:
                # 40% chance of NO orders (Pending)
                qty = 0
            elif chance < 0.7:
                # 30% chance of LOWER sales
                # Randomly 10 to 300
                qty = random.randint(1, 30) * 10
            else:
                # 30% chance of HIGHER sales
                # Randomly 400 to 900 (扩大范围，与Forecast区别更明显)
                qty = random.randint(40, 90) * 10

            row[month_col] = qty

        data.append(row)

    return data, date_columns

def save_to_excel(data, date_cols, filename="import_actuals_sample.xlsx"):
    if not data: return
    df = pd.DataFrame(data)
    cols = ['SKU', 'Product Name'] + date_cols
    df = df[cols]

    try:
        file_path = os.path.join(current_dir, filename)
        df.to_excel(file_path, index=False)
        print(f"\n✅ File Generated Successfully: {file_path}")
        print(f"   - Rows: {len(data)}")
    except PermissionError:
        print(f"\n❌ Error: Cannot write to '{filename}'.")
        print("   👉 Please CLOSE the Excel file and try again.")
    except Exception as e:
        print(f"❌ Failed to save Excel file: {e}")

if __name__ == "__main__":
    actual_data, cols = generate_actual_sales_data()
    save_to_excel(actual_data, cols)
