import os
import sys
import django
import pandas as pd
import random
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

# --- 1. Django Environment Setup ---
# 确保脚本可以找到 Django 项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventory.models import Product

# --- 2. Configuration ---
# Generate Actuals for the same range to allow comparison
MONTHS_TO_GENERATE = 6

def get_valid_fg_products():
    """
    Fetches the actual Product objects for Finished Goods (FG).
    """
    products = list(Product.objects.filter(nature='FG'))

    if not products:
        print("❌ Error: No 'FG' (Finished Goods) found in the database.")
        print("   Please run the inventory import first.")
        sys.exit(1)

    print(f"✅ Found {len(products)} valid FG items.")
    return products

def generate_actual_sales_data():
    """
    Generates a Matrix (Wide Format) dataset for ACTUAL ORDERS:
    SKU | Name | 2026-02-01 | 2026-03-01 | ...
    """
    products = get_valid_fg_products()

    # 1. Determine the date columns
    # (Aligning with Forecast script: Start next month)
    # This simulates "Future Orders" (Sales Orders) received in advance.
    today = date.today()
    start_month = today.replace(day=1) + relativedelta(months=1)

    date_columns = []
    for i in range(MONTHS_TO_GENERATE):
        current_month = start_month + relativedelta(months=i)
        date_columns.append(current_month.strftime('%Y-%m-%d'))

    data = []

    print(f"Generating Actual Sales (Orders) for months: {date_columns}")

    # 2. Build rows per SKU
    for product in products:
        row = {
            'SKU': product.sku,
            'Product Name': product.description,
        }

        # 3. Fill in random Actuals for each month
        for month_col in date_columns:
            # Logic:
            # - Some months have NO orders yet (Pending).
            # - Some months have orders slightly different from Forecast (Variance).

            chance = random.random()

            if chance < 0.4:
                # 40% chance of NO orders yet (Variance = -100%)
                qty = 0
            elif chance < 0.7:
                # 30% chance of LOWER than typical forecast (Under-selling)
                qty = random.randint(1, 30) * 10
            else:
                # 30% chance of HIGHER or ON PAR (Good sales / Spikes)
                qty = random.randint(40, 70) * 10

            row[month_col] = qty

        data.append(row)

    return data, date_columns

def save_to_excel(data, date_cols, filename="import_actuals_sample.xlsx"):
    if not data:
        return

    df = pd.DataFrame(data)

    # Reorder columns
    cols = ['SKU', 'Product Name'] + date_cols
    df = df[cols]

    try:
        file_path = os.path.join(current_dir, filename)
        df.to_excel(file_path, index=False)
        print(f"\n✅ File Generated Successfully: {file_path}")
        print(f"   - Rows: {len(data)}")
        print(f"   - Months: {', '.join(date_cols)}")
    except Exception as e:
        print(f"❌ Failed to save Excel file: {e}")

if __name__ == "__main__":
    try:
        actual_data, cols = generate_actual_sales_data()
        save_to_excel(actual_data, cols)

        print("\n--- How to Use ---")
        print("1. Go to your Web UI -> Forecast Dashboard")
        print("2. Click 'Import Actuals' (Blue Button)")
        print("3. In the form:")
        print("   - Country: Type 'Malaysia' (to match your forecast country) or 'Singapore' (to test multi-country)")
        print("   - File: Upload 'import_actuals_sample.xlsx'")
        print("4. Click Submit.")
        print("5. Check the 'Sales Forecast' table to see the comparison!")

    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
