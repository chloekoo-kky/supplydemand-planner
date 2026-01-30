import os
import django
import csv

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventory.models import Product

def generate_ingredients_csv(output_file='src/import_ingredients_sample.csv'):
    """
    Generates a sample CSV file containing recipe relationships (BOM)
    for the user to upload into the system.
    """
    # Define the recipe data structure
    # Format: (Parent SKU, Component SKU, Quantity, Notes)
    recipes = [
        # Vanilla Syrup Recipe
        ('FG-SYR-VAN', 'RAW-SUG-001', 0.8, 'Standard Recipe'),
        ('FG-SYR-VAN', 'RAW-WAT-FIL', 0.5, 'Standard Recipe'),
        ('FG-SYR-VAN', 'RAW-VAN-EXT', 0.02, 'Standard Recipe'),
        ('FG-SYR-VAN', 'PKG-BTL-GLS-750', 1.0, 'Standard Recipe'),
        ('FG-SYR-VAN', 'PKG-CAP-BLK', 1.0, 'Standard Recipe'),
        ('FG-SYR-VAN', 'PKG-LAB-VAN', 1.0, 'Standard Recipe'),

        # Hazelnut Syrup Recipe
        ('FG-SYR-HAZ', 'RAW-SUG-001', 0.75, 'Standard Recipe'),
        ('FG-SYR-HAZ', 'RAW-WAT-FIL', 0.55, 'Standard Recipe'),
        ('FG-SYR-HAZ', 'RAW-HAZ-EXT', 0.025, 'Standard Recipe'),
        ('FG-SYR-HAZ', 'PKG-BTL-GLS-750', 1.0, 'Standard Recipe'),
        ('FG-SYR-HAZ', 'PKG-CAP-WHT', 1.0, 'Standard Recipe'),
        ('FG-SYR-HAZ', 'PKG-LAB-HAZ', 1.0, 'Standard Recipe'),

        # Chocolate Sauce Recipe
        ('FG-SAU-COC', 'RAW-SUG-001', 0.5, 'Standard Recipe'),
        ('FG-SAU-COC', 'RAW-COC-POW', 0.15, 'Standard Recipe'),
        ('FG-SAU-COC', 'RAW-GLU-SYR', 0.2, 'Standard Recipe'),
        ('FG-SAU-COC', 'PKG-BTL-PET-1L', 1.0, 'Standard Recipe'),
        ('FG-SAU-COC', 'PKG-CAP-BLK', 1.0, 'Standard Recipe'),
        ('FG-SAU-COC', 'PKG-LAB-GEN', 1.0, 'Standard Recipe'),

        # Caramel Sauce Recipe
        ('FG-SAU-CAR', 'RAW-SUG-BRN', 0.6, 'Standard Recipe'),
        ('FG-SAU-CAR', 'RAW-GLU-SYR', 0.2, 'Standard Recipe'),
        ('FG-SAU-CAR', 'RAW-MLK-POW', 0.1, 'Standard Recipe'),
        ('FG-SAU-CAR', 'RAW-CAR-FLV', 0.02, 'Standard Recipe'),
        ('FG-SAU-CAR', 'PKG-BTL-PET-1L', 1.0, 'Standard Recipe'),
        ('FG-SAU-CAR', 'PKG-CAP-BLK', 1.0, 'Standard Recipe'),
        ('FG-SAU-CAR', 'PKG-LAB-GEN', 1.0, 'Standard Recipe'),

        # Lemon Tea Concentrate Recipe
        ('FG-CON-LEM', 'RAW-TEA-BLK', 0.1, 'Standard Recipe'),
        ('FG-CON-LEM', 'RAW-ACD-CIT', 0.05, 'Standard Recipe'),
        ('FG-CON-LEM', 'RAW-SUG-001', 0.4, 'Standard Recipe'),
        ('FG-CON-LEM', 'PKG-BTL-PET-1L', 1.0, 'Standard Recipe'),
        ('FG-CON-LEM', 'PKG-CAP-WHT', 1.0, 'Standard Recipe'),
        ('FG-CON-LEM', 'PKG-LAB-GEN', 1.0, 'Standard Recipe'),
    ]

    print(f"Generating {output_file}...")

    try:
        with open(output_file, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Write Header
            writer.writerow(['Parent SKU', 'Component SKU', 'Quantity', 'Notes'])

            # Write Recipe Rows
            for row in recipes:
                writer.writerow(row)

        print(f"✅ Success! Sample file created at: {output_file}")

    except Exception as e:
        print(f"❌ Error generating CSV: {e}")

if __name__ == "__main__":
    generate_ingredients_csv()
