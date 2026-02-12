FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/py/bin:$PATH"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    netcat-openbsd \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /py

COPY ./requirements.txt /tmp/requirements.txt
RUN /py/bin/pip install --upgrade pip && \
    /py/bin/pip install -r /tmp/requirements.txt && \
    rm -rf /tmp/requirements.txt

COPY ./src /app
COPY ./docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

RUN adduser --disabled-password --no-create-home django-user && \
    mkdir -p /vol/web/media && \
    mkdir -p /vol/web/static && \
    chown -R django-user:django-user /vol /app /py

USER django-user

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# Use Gunicorn for production by default
CMD ["gunicorn", "--bind", "0.0.0.0:7749", "config.wsgi:application"]
