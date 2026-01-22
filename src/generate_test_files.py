import pandas as pd
from weasyprint import HTML
import os

def generate_excel():
    print("Generating Excel test file...")

    data = {
        'Product SKU': [
            'RAW-SUG-001',
            'PKG-BOX-3030',
            'FG-VAN-750',
            'RAW-RIC-10',
            'NEW-ITEM-X'
        ],
        'Item Description': [
            'White Sugar (Refined)',
            'Cardboard Box 30x30',
            'Vanilla Syrup 750ml',
            'Rice 10kg Pack',
            'Unknown New Item',
        ],
        'Supplier': [               # [新增] Supplier 列
            'Gula Prai Sdn Bhd',    # Raw Material
            'Box Expert Ent',       # Packaging
            '',                     # Finished Good (通常没有外部供应商，或者是自己)
            'Bernas',               # Raw Material
            'Mystery Supply Co.'    # New Item
        ],
        'Total Quantity': [500, 200, 50, 45, 10],
        'Material Type': ['RAW', 'PKG', 'FG', 'RAW', 'RAW'],
        'Product Category': ['Ingredient', 'Packaging', 'Finished Product', 'Dry Goods', 'General'],
        'Unit Weight (kg)': [50, 0.5, 1.2, 10, 0],
        'Unit Volume (L)':  [0, 0, 0.75, 0, 0]
    }

    df = pd.DataFrame(data)

    filename = 'test_inventory_data.xlsx'
    df.to_excel(filename, index=False)
    print(f"✅ Excel generated: {filename}")

def generate_pdf():
    print("Generating PDF test file...")

    # [新增] 在 HTML 表格中增加 Supplier 列
    html_content = """
    <html>
    <head>
        <style>
            body { font-family: Helvetica, sans-serif; padding: 40px; }
            h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
            p { color: #7f8c8d; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; box-shadow: 0 2px 3px rgba(0,0,0,0.1); }
            th, td { border: 1px solid #e0e0e0; padding: 12px; text-align: left; font-size: 14px; }
            th { background-color: #f8f9fa; color: #2c3e50; font-weight: bold; }
            tr:nth-child(even) { background-color: #fdfdfd; }
        </style>
    </head>
    <body>
        <h1>Inventory Stock Report</h1>
        <p>Generated on: 2026-01-19 | Source: External Warehouse</p>

        <table>
            <thead>
                <tr>
                    <th>SKU Code</th>
                    <th>Item Description</th>
                    <th>Supplier</th> <th>Stock Qty</th>
                    <th>Nature Class</th>
                    <th>Weight (kg)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>RAW-SUG-BAG</td>
                    <td>Raw Sugar 50kg Bag</td>
                    <td>Gula Prai Sdn Bhd</td> <td>150</td>
                    <td>RAW</td>
                    <td>45.0</td>
                </tr>
                <tr>
                    <td>PKG-BTL-001</td>
                    <td>Plastic Bottle 1L (Clear)</td>
                    <td>Plastic Tech Solutions</td> <td>5000</td>
                    <td>PKG</td>
                    <td>0.05</td>
                </tr>
                <tr>
                    <td>FG-SYR-HAZ</td>
                    <td>Hazelnut Syrup 1L</td>
                    <td>-</td>
                    <td>80</td>
                    <td>FG</td>
                    <td>1.4</td>
                </tr>
                <tr>
                    <td>RAW-OIL-005</td>
                    <td>Cooking Oil 5kg</td>
                    <td>Saji Oils</td>
                    <td>25</td>
                    <td>RAW</td>
                    <td>5.0</td>
                </tr>
                 <tr>
                    <td>RAW-COC-PREM</td>
                    <td>Cocoa Powder Premium</td>
                    <td>Barry Callebaut</td>
                    <td>300</td>
                    <td>RAW</td>
                    <td>25</td>
                </tr>
            </tbody>
        </table>

        <div style="margin-top: 30px; font-size: 12px; color: #999;">
            *End of Report*
        </div>
    </body>
    </html>
    """

    filename = 'test_inventory_data.pdf'
    HTML(string=html_content).write_pdf(filename)
    print(f"✅ PDF generated: {filename}")

if __name__ == "__main__":
    try:
        generate_excel()
        generate_pdf()
        print("\n🎉 All test files generated successfully!")
    except Exception as e:
        print(f"❌ Error: {e}")
