# 使用官方轻量级 Python 镜像
FROM python:3.11-slim-bookworm

# 设置 Python 环境变量
# PYTHONUNBUFFERED=1: 确保日志即时输出，方便 Docker logs 查看
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/py/bin:$PATH"

# 设置工作目录
WORKDIR /app

# 安装系统依赖
# 1. build-essential & libpq-dev: 用于编译 psycopg2 (Postgres驱动)
# 2. netcat-openbsd: 用于 entrypoint.sh 检测数据库端口
# 3. libpango...: 用于 WeasyPrint 生成 PDF (处理 Invoice/PO 单据必备)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    netcat-openbsd \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境
RUN python -m venv /py

# 复制并安装依赖
# 注意: 我们先复制 requirements.txt，利用 Docker 缓存机制加速构建
COPY ./requirements.txt /tmp/requirements.txt
RUN /py/bin/pip install --upgrade pip && \
    /py/bin/pip install -r /tmp/requirements.txt && \
    rm -rf /tmp/requirements.txt

# 复制项目代码
COPY ./src /app
# 复制 entrypoint 脚本
COPY ./docker/entrypoint.sh /entrypoint.sh

# 关键：赋予脚本执行权限
RUN chmod +x /entrypoint.sh

# 创建非 root 用户 (安全最佳实践)
# 并在创建用户后，赋予其对静态文件目录的权限
RUN adduser --disabled-password --no-create-home django-user && \
    mkdir -p /vol/web/media && \
    mkdir -p /vol/web/static && \
    chown -R django-user:django-user /vol /app /py

# 切换到非 root 用户
USER django-user

# 暴露端口
EXPOSE 8000

# 设置入口点
ENTRYPOINT ["/entrypoint.sh"]

# 默认启动命令
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
