import pandas as pd
from weasyprint import HTML
import os
from datetime import datetime

# --- Data Configuration ---

def get_test_data():
    """
    Generates a list of dictionaries containing 50 test items:
    - 20 Raw Materials
    - 10 Packaging & Labels
    - 20 Finished Goods
    """
    data = []

    # Helper to add rows
    def add_row(sku, name, supplier, qty, nature, cat, weight, vol, uom, cost, moq, lead, usage):
        data.append({
            'Product SKU': sku,
            'Item Description': name,
            'Supplier': supplier,
            'Total Quantity': qty,
            'Material Type': nature, # RAW, PKG, FG (Nature)
            'Product Category': cat, # Ingredient, Syrups, Container (Form)
            'Unit Weight (kg)': weight,
            'Unit Volume (L)': vol,
            'UOM': uom,
            'Cost Price': cost,
            'MOQ': moq,
            'Lead Time (Days)': lead,
            'Daily Usage': usage
        })

    # 1. Raw Materials (20 items)
    raw_materials = [
        ('RAW-SUG-001', 'White Sugar (Refined)', 'Gula Prai Sdn Bhd', 5000, 'Ingredient', 50.0, 0, 'KG', 2.50, 100, 7, 50),
        ('RAW-SUG-BRN', 'Brown Sugar', 'Gula Prai Sdn Bhd', 1200, 'Ingredient', 25.0, 0, 'KG', 3.20, 50, 7, 10),
        ('RAW-GLU-SYR', 'Glucose Syrup', 'ChemSource Inc', 800, 'Ingredient', 25.0, 20.0, 'KG', 5.50, 200, 14, 15),
        ('RAW-WAT-FIL', 'Filtered Water (Industrial)', 'Utility Provider', 10000, 'Liquid', 1.0, 1.0, 'L', 0.10, 0, 0, 500),
        ('RAW-VAN-EXT', 'Vanilla Extract Premium', 'Flavor House Ltd', 150, 'Flavoring', 5.0, 5.0, 'L', 120.00, 20, 30, 2),
        ('RAW-HAZ-EXT', 'Hazelnut Extract', 'Flavor House Ltd', 80, 'Flavoring', 5.0, 5.0, 'L', 145.00, 10, 30, 1.5),
        ('RAW-CAR-FLV', 'Caramel Flavoring', 'Flavor House Ltd', 95, 'Flavoring', 5.0, 5.0, 'L', 110.00, 10, 30, 1.8),
        ('RAW-COC-POW', 'Cocoa Powder (Dutch Process)', 'Barry Callebaut', 600, 'Ingredient', 25.0, 0, 'KG', 35.00, 100, 45, 12),
        ('RAW-MLK-POW', 'Skimmed Milk Powder', 'Dairy Suppliers Co', 400, 'Ingredient', 25.0, 0, 'KG', 28.00, 50, 21, 8),
        ('RAW-COF-ARA', 'Arabica Coffee Beans', 'Bean Importers', 1500, 'Bean', 60.0, 0, 'KG', 45.00, 300, 60, 25),
        ('RAW-COF-ROB', 'Robusta Coffee Beans', 'Bean Importers', 2000, 'Bean', 60.0, 0, 'KG', 25.00, 300, 60, 30),
        ('RAW-TEA-BLK', 'Black Tea Dust', 'Tea Garden Cameron', 800, 'Leaf', 10.0, 0, 'KG', 18.00, 100, 14, 15),
        ('RAW-TEA-GRN', 'Green Tea Matcha', 'Kyoto Import', 50, 'Leaf', 1.0, 0, 'KG', 250.00, 10, 60, 0.5),
        ('RAW-PRE-BEN', 'Sodium Benzoate', 'ChemSource Inc', 100, 'Additive', 25.0, 0, 'KG', 15.00, 25, 14, 0.2),
        ('RAW-ACD-CIT', 'Citric Acid Anhydrous', 'ChemSource Inc', 250, 'Additive', 25.0, 0, 'KG', 8.50, 50, 14, 1.0),
        ('RAW-COL-RED', 'Food Coloring E129 (Red)', 'Colorant Co', 20, 'Additive', 1.0, 1.0, 'L', 85.00, 5, 21, 0.1),
        ('RAW-COL-BLU', 'Food Coloring E133 (Blue)', 'Colorant Co', 15, 'Additive', 1.0, 1.0, 'L', 90.00, 5, 21, 0.05),
        ('RAW-SAL-SEA', 'Sea Salt (Fine)', 'Salt Supplier', 300, 'Ingredient', 50.0, 0, 'KG', 1.20, 100, 7, 4),
        ('RAW-EMU-LEC', 'Soy Lecithin', 'ChemSource Inc', 120, 'Additive', 20.0, 20.0, 'KG', 22.00, 20, 21, 0.8),
        ('RAW-SPI-CIN', 'Cinnamon Powder', 'Spices & Co', 60, 'Spice', 5.0, 0, 'KG', 65.00, 10, 14, 0.3),
    ]

    for sku, name, supp, qty, cat, w, v, uom, cost, moq, lead, use in raw_materials:
        add_row(sku, name, supp, qty, 'RAW', cat, w, v, uom, cost, moq, lead, use)

    # 2. Packaging (10 items)
    pkg_materials = [
        ('PKG-BTL-GLS-750', 'Glass Bottle 750ml (Clear)', 'Glass Works Ltd', 5000, 'Container', 0.45, 0, 'PCS', 1.50, 2000, 45, 200),
        ('PKG-BTL-PET-1L',  'PET Bottle 1L (Round)', 'Plastic Tech', 12000, 'Container', 0.05, 0, 'PCS', 0.60, 5000, 21, 400),
        ('PKG-CAP-BLK',     'Screw Cap 28mm (Black)', 'Plastic Tech', 20000, 'Closure', 0.005, 0, 'PCS', 0.05, 10000, 21, 600),
        ('PKG-CAP-WHT',     'Screw Cap 28mm (White)', 'Plastic Tech', 15000, 'Closure', 0.005, 0, 'PCS', 0.05, 10000, 21, 400),
        ('PKG-LAB-VAN',     'Label - Vanilla Syrup', 'Print Press', 8000, 'Label', 0.001, 0, 'PCS', 0.08, 5000, 14, 150),
        ('PKG-LAB-HAZ',     'Label - Hazelnut Syrup', 'Print Press', 5000, 'Label', 0.001, 0, 'PCS', 0.08, 3000, 14, 80),
        ('PKG-LAB-GEN',     'Label - Generic Back', 'Print Press', 20000, 'Label', 0.001, 0, 'PCS', 0.04, 10000, 14, 300),
        ('PKG-BOX-6X750',   'Carton Box (6 x 750ml)', 'Box Expert Ent', 1500, 'Carton', 0.30, 0, 'PCS', 1.20, 500, 14, 50),
        ('PKG-SHR-WRP',     'Shrink Wrap Roll (Heavy)', 'Plastic Tech', 50, 'Consumable', 5.0, 0, 'ROLL', 45.00, 10, 7, 0.5),
        ('PKG-PAL-WOO',     'Wooden Pallet (Standard)', 'Warehouse Supply', 40, 'Logistics', 15.0, 0, 'PCS', 80.00, 10, 3, 0.1),
    ]

    for sku, name, supp, qty, cat, w, v, uom, cost, moq, lead, use in pkg_materials:
        add_row(sku, name, supp, qty, 'PKG', cat, w, v, uom, cost, moq, lead, use)

    # 3. Finished Goods (20 items)
    fg_items = [
        ('FG-SYR-VAN', 'Vanilla Syrup 750ml', '', 240, 'Syrups', 1.35, 0.75, 'BTL', 8.50, 0, 1, 48),
        ('FG-SYR-HAZ', 'Hazelnut Syrup 750ml', '', 180, 'Syrups', 1.35, 0.75, 'BTL', 9.00, 0, 1, 36),
        ('FG-SYR-CAR', 'Caramel Syrup 750ml', '', 200, 'Syrups', 1.38, 0.75, 'BTL', 8.80, 0, 1, 40),
        ('FG-SAU-COC', 'Chocolate Sauce 1L', '', 150, 'Sauces', 1.45, 1.00, 'BTL', 15.00, 0, 2, 20),
        ('FG-SAU-CAR', 'Caramel Sauce 1L', '', 120, 'Sauces', 1.45, 1.00, 'BTL', 14.50, 0, 2, 15),
        ('FG-SYR-STR', 'Strawberry Syrup 750ml', '', 90, 'Syrups', 1.35, 0.75, 'BTL', 9.50, 0, 1, 12),
        ('FG-SYR-PEA', 'Peach Syrup 750ml', '', 85, 'Syrups', 1.35, 0.75, 'BTL', 9.50, 0, 1, 10),
        ('FG-PUR-MAN', 'Mango Puree 1L', '', 60, 'Puree', 1.20, 1.00, 'BTL', 18.00, 0, 2, 8),
        ('FG-SYR-BLU', 'Blue Curacao Syrup 750ml', '', 100, 'Syrups', 1.35, 0.75, 'BTL', 10.00, 0, 1, 15),
        ('FG-SYR-PEP', 'Peppermint Syrup 750ml', '', 50, 'Syrups', 1.35, 0.75, 'BTL', 9.20, 0, 1, 5),
        ('FG-SYR-COC', 'Coconut Syrup 750ml', '', 70, 'Syrups', 1.35, 0.75, 'BTL', 9.20, 0, 1, 8),
        ('FG-SYR-ALM', 'Almond Syrup 750ml', '', 45, 'Syrups', 1.35, 0.75, 'BTL', 11.00, 0, 1, 4),
        ('FG-SYR-IRI', 'Irish Cream Syrup 750ml', '', 110, 'Syrups', 1.35, 0.75, 'BTL', 10.50, 0, 1, 18),
        ('FG-SYR-SLC', 'Salted Caramel Syrup 750ml', '', 130, 'Syrups', 1.38, 0.75, 'BTL', 9.50, 0, 1, 24),
        ('FG-SYR-RAS', 'Raspberry Syrup 750ml', '', 40, 'Syrups', 1.35, 0.75, 'BTL', 9.80, 0, 1, 6),
        ('FG-CON-LEM', 'Lemon Tea Concentrate 1L', '', 300, 'Concentrate', 1.10, 1.00, 'BTL', 12.00, 0, 1, 50),
        ('FG-CON-GRN', 'Green Tea Concentrate 1L', '', 250, 'Concentrate', 1.10, 1.00, 'BTL', 13.50, 0, 1, 45),
        ('FG-BAS-COF', 'Coffee Base Concentrate', '', 500, 'Base', 20.0, 20.0, 'DRUM', 180.00, 0, 1, 10),
        ('FG-SYR-TOF', 'Toffee Nut Syrup 750ml', '', 95, 'Syrups', 1.35, 0.75, 'BTL', 10.20, 0, 1, 12),
        ('FG-SYR-ROS', 'Rose Syrup 750ml', '', 80, 'Syrups', 1.35, 0.75, 'BTL', 8.50, 0, 1, 10),
    ]

    for sku, name, supp, qty, cat, w, v, uom, cost, moq, lead, use in fg_items:
        add_row(sku, name, supp, qty, 'FG', cat, w, v, uom, cost, moq, lead, use)

    return data

# --- Generators ---

def generate_excel(data):
    print("Generating Excel test file...")
    df = pd.DataFrame(data)
    filename = 'test_inventory_data.xlsx'
    df.to_excel(filename, index=False)
    print(f"✅ Excel generated: {filename}")

def generate_pdf(data):
    print("Generating PDF test file...")

    # Build rows dynamically
    rows_html = ""
    for item in data:
        # Determine color class based on type
        row_style = ""
        if item['Material Type'] == 'FG':
            row_style = 'style="background-color: #f0f9ff;"' # Light Blue for FG
        elif item['Material Type'] == 'PKG':
            row_style = 'style="background-color: #fdf4ff;"' # Light Purple for PKG

        rows_html += f"""
        <tr {row_style}>
            <td>{item['Product SKU']}</td>
            <td>{item['Item Description']}</td>
            <td>{item['Supplier']}</td>
            <td>{item['Total Quantity']}</td>
            <td>{item['Material Type']}</td>
            <td>{item['Product Category']}</td>
            <td>{item['Unit Weight (kg)']}</td>
            <td>{item['Lead Time (Days)']}</td>
            <td>{item['Cost Price']}</td>
        </tr>
        """

    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Helvetica, sans-serif; padding: 20px; }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            p {{ color: #7f8c8d; margin-bottom: 20px; font-size: 12px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 10px; }}
            th, td {{ border: 1px solid #e0e0e0; padding: 8px; text-align: left; }}
            th {{ background-color: #34495e; color: #ffffff; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>Inventory Stock Report</h1>
        <p>Generated on: {datetime.now().strftime('%Y-%m-%d')} | Source: System Export</p>
        <p>Total Items: {len(data)}</p>

        <table>
            <thead>
                <tr>
                    <th>SKU Code</th>
                    <th>Item Description</th>
                    <th>Supplier</th>
                    <th>Qty</th>
                    <th>Type</th>
                    <th>Category</th>
                    <th>Wgt (kg)</th>
                    <th>Lead Time</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div style="margin-top: 30px; font-size: 10px; color: #999; text-align: center;">
            * End of Report *
        </div>
    </body>
    </html>
    """

    filename = 'test_inventory_data.pdf'
    HTML(string=html_content).write_pdf(filename)
    print(f"✅ PDF generated: {filename}")

if __name__ == "__main__":
    try:
        test_data = get_test_data()
        generate_excel(test_data)
        generate_pdf(test_data)
        print("\n🎉 All 50 test files generated successfully!")
    except Exception as e:
        print(f"❌ Error: {e}")
