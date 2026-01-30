import pandas as pd
import random
from datetime import datetime, timedelta
import os
import django

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventory.models import Product

def create_products():
    """
    Creates the Master Data (Products) needed for the BOM import.
    """
    products = [
        # --- FINISHED GOODS ---
        ('FG-SYR-VAN', 'Vanilla Syrup 750ml', 'FG', 'BTL'),
        ('FG-SYR-HAZ', 'Hazelnut Syrup 750ml', 'FG', 'BTL'),
        ('FG-SAU-CAR', 'Caramel Sauce 1L', 'FG', 'BTL'),
        ('FG-SAU-COC', 'Chocolate Sauce 1L', 'FG', 'BTL'),
        ('FG-CON-LEM', 'Lemon Tea Concentrate 1L', 'FG', 'BTL'),

        # --- RAW MATERIALS (Ingredients) ---
        ('RAW-SUG-001', 'White Sugar Standard', 'RM', 'KG'),
        ('RAW-SUG-BRN', 'Brown Sugar Premium', 'RM', 'KG'),
        ('RAW-WAT-FIL', 'Filtered Water', 'RM', 'L'),
        ('RAW-VAN-EXT', 'Vanilla Extract Premium', 'RM', 'L'),
        ('RAW-HAZ-EXT', 'Hazelnut Extract', 'RM', 'L'),
        ('RAW-GLU-SYR', 'Glucose Syrup', 'RM', 'KG'),
        ('RAW-MLK-POW', 'Milk Powder Full Cream', 'RM', 'KG'),
        ('RAW-CAR-FLV', 'Caramel Flavoring', 'RM', 'L'),
        ('RAW-COC-POW', 'Cocoa Powder', 'RM', 'KG'),
        ('RAW-TEA-BLK', 'Black Tea Extract', 'RM', 'L'),
        ('RAW-ACD-CIT', 'Citric Acid', 'RM', 'KG'),

        # --- PACKAGING ---
        ('PKG-BTL-GLS-750', 'Glass Bottle 750ml Clear', 'RM', 'EA'),
        ('PKG-BTL-PET-1L',  'PET Bottle 1L', 'RM', 'EA'),
        ('PKG-CAP-BLK', 'Cap Black Standard', 'RM', 'EA'),
        ('PKG-CAP-WHT', 'Cap White Standard', 'RM', 'EA'),
        ('PKG-LAB-VAN', 'Label Vanilla 750ml', 'RM', 'EA'),
        ('PKG-LAB-HAZ', 'Label Hazelnut 750ml', 'RM', 'EA'),
        ('PKG-LAB-GEN', 'Label Generic Brand', 'RM', 'EA'),
    ]

    print("Creating/Updating Products...")
    for sku, desc, nature, uom in products:
        p, created = Product.objects.get_or_create(
            sku=sku,
            defaults={
                'description': desc,
                'nature': nature,
                'uom': uom,
                'unit_weight': 1.0 if uom == 'KG' else 0,
                'unit_volume': 1.0 if uom == 'L' else 0,
            }
        )
        if created:
            print(f"✅ Created: {sku}")
        else:
            print(f"ℹ️ Exists: {sku}")

if __name__ == "__main__":
    create_products()
    print("\nDone! You can now run the BOM Import.")
