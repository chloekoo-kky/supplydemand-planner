import os
import sys
import django
import pandas as pd
import random
from datetime import datetime, timedelta

# --- 1. Django Environment Setup ---
# This allows us to query your actual database so we don't guess SKUs.
current_dir = os.path.dirname(os.path.abspath(__file__))
# Add 'src' to python path so we can import 'config' and 'inventory'
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Now we can import models safely
from inventory.models import Product

# --- 2. Configuration ---

COUNTRIES = [
    'Malaysia', 'Singapore', 'Thailand', 'Vietnam',
    'Indonesia', 'Philippines', 'Australia', 'Japan'
]

def get_valid_skus():
    """
    Fetches the list of valid Finished Goods (FG) SKUs directly from the database.
    """
    # Filter only products marked as 'FG' (Finished Good)
    skus = list(Product.objects.filter(nature='FG').values_list('sku', flat=True))

    if not skus:
        print("❌ Error: No 'FG' (Finished Goods) found in the database.")
        print("   Please run the inventory import first or check your product data.")
        sys.exit(1)

    print(f"✅ Found {len(skus)} valid FG items in database.")
    return skus

def generate_forecast_data(num_rows=100):
    """
    Generates random forecast entries using REAL SKUs from the DB.
    """
    # Get SKUs from DB
    valid_skus = get_valid_skus()

    data = []
    start_date = datetime.now()

    print(f"Generating {num_rows} forecast lines...")

    for i in range(num_rows):
        # 1. Select a valid SKU
        sku = random.choice(valid_skus)

        # 2. Select a random Country
        country = random.choice(COUNTRIES)

        # 3. Random ETA: Between 7 to 90 days from now
        days_ahead = random.randint(7, 90)
        eta_date = start_date + timedelta(days=days_ahead)

        # 4. Random Quantity (Simulate carton logic)
        if country in ['Malaysia', 'Singapore']:
            base_qty = random.randint(50, 200) # Higher demand markets
        else:
            base_qty = random.randint(10, 80)  # Emerging markets

        quantity = base_qty * 12

        data.append({
            'SKU': sku,
            'Country': country,
            'ETA': eta_date.strftime('%Y-%m-%d'),
            'Quantity': quantity
        })

    return data

def save_to_excel(data, filename="test_forecast_data.xlsx"):
    if not data:
        return

    df = pd.DataFrame(data)

    # Sort by ETA for better readability
    df['ETA'] = pd.to_datetime(df['ETA'])
    df = df.sort_values(by='ETA')

    # Save file
    try:
        # Save in the same directory as the script
        file_path = os.path.join(current_dir, filename)
        df.to_excel(file_path, index=False)
        print(f"✅ Forecast File Generated: {file_path}")
        print(f"   - Contains {len(data)} rows")
        print(f"   - Date Range: {df['ETA'].min().date()} to {df['ETA'].max().date()}")
    except Exception as e:
        print(f"❌ Failed to save Excel file: {e}")

if __name__ == "__main__":
    try:
        # Run the generation
        forecast_data = generate_forecast_data(num_rows=150)
        save_to_excel(forecast_data)

        print("\nInstructions:")
        print("1. Go to your Web UI -> Production Forecasts")
        print("2. Click 'Import New Plan'")
        print("3. Upload 'test_forecast_data.xlsx'")
        print("4. The system should now accept all rows without 'SKU not found' errors.")

    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
