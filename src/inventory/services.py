import pandas as pd
import pdfplumber
from rapidfuzz import process, fuzz
from .models import Product

def extract_data_from_file(file_obj):
    """
    智能文件解析器：支持 Excel (.xlsx) 和 PDF
    返回: DataFrame (包含 'description', 'quantity' 等列)
    """
    filename = file_obj.name.lower()

    if filename.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(file_obj)

    elif filename.endswith('.pdf'):
        data = []
        with pdfplumber.open(file_obj) as pdf:
            for page in pdf.pages:
                # 尝试提取每一页的表格
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        # 简单的清洗：去掉空行
                        cleaned_row = [cell.strip() if cell else '' for cell in row]
                        if any(cleaned_row): # 如果这一行不全是空
                            data.append(cleaned_row)

        # 假设 PDF 表格的第一行是表头 (Header)
        if data:
            headers = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=headers)
        else:
            return None # 无法提取表格

    else:
        raise ValueError("Unsupported file format")

    # 标准化列名 (Normalization)
    # 尝试把各种奇葩列名映射到标准列名
    column_map = {}
    for col in df.columns:
        col_lower = str(col).lower()

        if 'sku' in col_lower or 'code' in col_lower or 'id' in col_lower:
             column_map[col] = 'import_sku'
        elif 'desc' in col_lower or 'item' in col_lower or 'product' in col_lower:
            column_map[col] = 'import_description'
        elif 'qty' in col_lower or 'quantity' in col_lower:
            column_map[col] = 'import_qty'
        elif 'nature' in col_lower or 'type' in col_lower or 'class' in col_lower:
            column_map[col] = 'import_nature'
        elif 'cat' in col_lower or 'category' in col_lower or 'form' in col_lower:
            column_map[col] = 'import_category'
        elif 'weight' in col_lower or 'kg' in col_lower:
            column_map[col] = 'import_weight'
        elif 'volume' in col_lower or 'liter' in col_lower or 'litre' in col_lower or 'vol' in col_lower:
             column_map[col] = 'import_volume'
        elif 'supp' in col_lower or 'vendor' in col_lower:
             column_map[col] = 'import_supplier'
        elif 'price' in col_lower or 'cost' in col_lower or 'amount' in col_lower or 'rm' in col_lower:
             column_map[col] = 'import_price'

    df = df.rename(columns=column_map)

    # 确保只要有这两列就保留，其他的列先忽略
    required_cols = ['import_description', 'import_qty']
    if not all(col in df.columns for col in required_cols):
        # 如果找不到列，可以抛错或者让用户手动映射 (这里先简单处理，抛错)
        # 实际项目中，你可以返回原始 DataFrame 让用户在前端选列
        pass

    return df

def calculate_matching_score(import_df):
    """
    核心算法：计算每一行导入数据与数据库中 Product 的相似度
    """
    # 1. 获取所有现有产品的 SKU 和 描述
    # 格式: { 'SKU001 - Coke': <Product Object>, ... }
    existing_products = {
        f"{p.description}": p for p in Product.objects.all()
    }
    choices = list(existing_products.keys())

    results = []

    for _, row in import_df.iterrows():
        import_desc = str(row.get('import_description', ''))
        import_qty = row.get('import_qty', 0)

        if not import_desc:
            continue

        # 2. 使用 RapidFuzz 寻找最佳匹配 (Best Match)
        # process.extractOne 会返回: (match_string, score, index)
        match = process.extractOne(import_desc, choices, scorer=fuzz.WRatio)

        best_match_product = None
        score = 0

        if match:
            match_str, score, _ = match
            best_match_product = existing_products[match_str]

        results.append({
            'import_description': import_desc,
            'import_qty': import_qty,
            'matched_product_id': best_match_product.id if best_match_product else None,
            'matched_product_sku': best_match_product.sku if best_match_product else 'N/A',
            'matched_product_desc': best_match_product.description if best_match_product else 'No Match',
            'match_score': round(score, 1) # 保留一位小数 (e.g., 95.5)
        })

    return results
