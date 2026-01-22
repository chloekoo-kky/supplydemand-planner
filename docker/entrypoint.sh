#!/bin/sh

# 如果任何指令执行失败，立即退出脚本 (Exit on error)
set -e

# 检查环境变量 DATABASE 是否为 postgres
if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    # 循环检查数据库端口 (5432) 是否开启
    # nc (netcat) 是在 Dockerfile 里安装的工具
    while ! nc -z $DB_HOST $DB_PORT; do
      sleep 0.1
    done

    echo "PostgreSQL started"
fi

# 自动运行数据库迁移 (在开发环境中非常方便)
# 生产环境通常建议手动运行，但在 MVP 快速迭代阶段，自动运行能省很多事
echo "Running migrations..."
python manage.py migrate

# 收集静态文件 (将 Admin 的 CSS/JS 收集到 static_volume)
# 如果发现启动太慢，可以注释掉这一行，手动运行
echo "Collecting static files..."
python manage.py collectstatic --noinput

# 执行 Dockerfile CMD 中传入的命令 (即启动服务器)
exec "$@"
