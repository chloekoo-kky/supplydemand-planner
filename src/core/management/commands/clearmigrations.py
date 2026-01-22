import os
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = '清除指定 APP 下的所有 migrations 文件 (保留 __init__.py)'

    def handle(self, *args, **options):
        # === 配置：在这里指定你需要清理的 APP 名字 ===
        TARGET_APPS = ['inventory', 'core']

        # 确认项目根目录 (src/)
        base_dir = settings.BASE_DIR

        self.stdout.write(self.style.WARNING(f"准备清除以下 APP 的迁移文件: {', '.join(TARGET_APPS)}"))

        for app in TARGET_APPS:
            # 构建 migrations 文件夹路径
            migrations_dir = os.path.join(base_dir, app, 'migrations')

            if not os.path.exists(migrations_dir):
                self.stdout.write(self.style.WARNING(f"⚠️  跳过 {app}: 找不到 migrations 目录"))
                continue

            # 遍历目录下的所有文件
            deleted_count = 0
            for filename in os.listdir(migrations_dir):
                # 绝对保留 __init__.py
                if filename == '__init__.py':
                    continue

                # 忽略非 .py 文件和非文件夹 (但也清理 __pycache__)
                file_path = os.path.join(migrations_dir, filename)

                try:
                    if os.path.isfile(file_path) and (filename.endswith('.py') or filename.endswith('.pyc')):
                        os.remove(file_path)
                        deleted_count += 1
                    elif os.path.isdir(file_path) and filename == '__pycache__':
                        shutil.rmtree(file_path)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"❌ 删除失败: {filename} - {e}"))

            if deleted_count > 0:
                self.stdout.write(self.style.SUCCESS(f"✅ {app}: 已删除 {deleted_count} 个迁移文件"))
            else:
                self.stdout.write(f"   {app}: 没有需要删除的文件")

        self.stdout.write(self.style.SUCCESS("\n所有清理完成！建议接下来执行数据库重置。"))
