import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import seaborn as sns

# 设置风格
plt.style.use('dark_background')
sns.set_context("talk")

# 1. 准备模拟数据
months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
forecast = [120, 135, 145, 160, 155, 180, 195, 210, 205, 230, 250, 270]
actuals =  [115, 140, 142, 158, 160, 185, 190, 215, 200, 235, 245, 275]
inventory = [300, 280, 260, 320, 300, 280, 400, 380, 360, 340, 500, 480]

df = pd.DataFrame({
    'Month': months,
    'Forecast': forecast,
    'Actuals': actuals,
    'Inventory': inventory
})

# 2. 创建画布 (16:9 比例，适合 LinkedIn)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 9))
fig.suptitle('Supply & Demand Planner Dashboard', fontsize=30, color='#4db6ac', fontweight='bold', y=0.95)

# 调整背景色，使其看起来更像现代 UI
fig.patch.set_facecolor('#0f172a') # 深海军蓝背景
ax1.set_facecolor('#1e293b')
ax2.set_facecolor('#1e293b')

# 3. 绘制图表 1: Forecast vs Actuals (折线图)
ax1.plot(months, forecast, marker='o', linestyle='--', color='#94a3b8', label='Forecast', linewidth=3)
ax1.plot(months, actuals, marker='o', linestyle='-', color='#2dd4bf', label='Actual Sales', linewidth=3)
ax1.set_title('Sales Performance', fontsize=20, color='white', pad=20)
ax1.legend(frameon=True, facecolor='#1e293b', edgecolor='white')
ax1.grid(True, linestyle=':', alpha=0.3)
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)

# 4. 绘制图表 2: Inventory Levels (柱状图)
colors = ['#f43f5e' if x < 300 else '#3b82f6' for x in inventory] # 低于 300 标红
ax2.bar(months, inventory, color=colors, alpha=0.8)
ax2.axhline(y=300, color='#f43f5e', linestyle='--', alpha=0.5, label='Safety Stock')
ax2.set_title('Inventory Levels', fontsize=20, color='white', pad=20)
ax2.legend(frameon=True, facecolor='#1e293b', edgecolor='white')
ax2.grid(True, axis='y', linestyle=':', alpha=0.3)
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)

# 5. 添加底部技术栈标签
plt.figtext(0.5, 0.05, 'Built with: Django | Docker | Pandas', ha='center', fontsize=16, color='#94a3b8')

# 6. 保存
plt.tight_layout(rect=[0, 0.08, 1, 0.9])
plt.savefig('project_thumbnail.png', dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
print("Thumbnail generated successfully!")
