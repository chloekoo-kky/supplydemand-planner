import os
import sys
import django
import pandas as pd
import random
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
# Generate forecast for the next X months
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

def generate_wide_format_forecast():
    """
    Generates a Matrix (Wide Format) dataset:
    SKU | Name | 2026-02-01 | 2026-03-01 | ...
    """
    products = get_valid_fg_products()

    # 1. Determine the date columns (Next 6 months, starting next month)
    today = date.today()
    start_month = today.replace(day=1) + relativedelta(months=1) # Start next month

    date_columns = []
    for i in range(MONTHS_TO_GENERATE):
        current_month = start_month + relativedelta(months=i)
        # Use YYYY-MM-DD format as it's safe for pd.to_datetime
        date_columns.append(current_month.strftime('%Y-%m-%d'))

    data = []

    print(f"Generating forecast for months: {date_columns}")

    # 2. Build rows per SKU
    for product in products:
        row = {
            'SKU': product.sku,
            'Product Name': product.description, # Optional, helps readability
        }

        # 3. Fill in random demand for each month
        for month_col in date_columns:
            # Random logic: 30% chance of 0 demand, otherwise 50-500 units
            if random.random() < 0.3:
                qty = 0
            else:
                qty = random.randint(5, 50) * 10 # round numbers e.g., 50, 60... 500

            row[month_col] = qty

        data.append(row)

    return data, date_columns

def save_to_excel(data, date_cols, filename="sales_forecast_sample.xlsx"):
    if not data:
        return

    df = pd.DataFrame(data)

    # Reorder columns to ensure SKU and Name are first
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
        forecast_data, cols = generate_wide_format_forecast()
        save_to_excel(forecast_data, cols)

        print("\n--- How to Use ---")
        print("1. Go to your Web UI -> Forecast Dashboard")
        print("2. Click 'Import Demand'")
        print("3. In the form:")
        print("   - Country: Type 'Malaysia' (or any target market)")
        print("   - File: Upload 'import_demand_sample.xlsx'")
        print("4. Click Submit.")

    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
