FROM nginx:1.28-alpine
ENV BACKEND_UPSTREAM=backend:8000 NGINX_RESOLVER=127.0.0.11
# Substitute only deployment inputs, preserving native nginx variables.
ENV NGINX_ENVSUBST_FILTER="^(BACKEND_UPSTREAM|NGINX_RESOLVER)$"
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY lab/ /usr/share/nginx/html/lab/
COPY assets/icons/ /usr/share/nginx/html/assets/icons/
COPY assets/league/ /usr/share/nginx/html/assets/league/
COPY match/ /tmp/frontend/match/
COPY tools/build.sh /tmp/frontend/tools/build.sh
RUN sh /tmp/frontend/tools/build.sh /usr/share/nginx/html && rm -rf /tmp/frontend
