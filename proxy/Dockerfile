FROM nginxinc/nginx-unprivileged:1-alpine

COPY ./default.conf /etc/nginx/conf.d/default.conf

USER root
# Create directories and set permissions for static/media
# Note: These must match STATIC_ROOT/MEDIA_ROOT locations in Django
RUN mkdir -p /vol/web/static && chmod 755 /vol/web/static && \
    mkdir -p /vol/web/media && chmod 755 /vol/web/media && \
    chown -R nginx:nginx /vol

USER nginx
