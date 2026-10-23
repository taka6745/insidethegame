FROM node:24-alpine AS build
WORKDIR /frontend
COPY package.json package-lock.json .npmrc tsconfig.json ./
RUN npm ci --ignore-scripts
COPY shared/ shared/
COPY match/ match/
COPY lab/ lab/
COPY dev/ dev/
COPY tools/build.sh tools/vendor.sh tools/
RUN npm run build && sh tools/build.sh /site dist && cp -R dist/lab dist/dev dist/shared /site/

FROM nginx:1.28-alpine
ENV BACKEND_UPSTREAM=backend:8000 NGINX_RESOLVER=127.0.0.11 MEDIA_ORIGIN=feed:8000 \
    FEED_ADMIN_UPSTREAM=feed:8000 DEMO_CONTROL_UPSTREAM=demo-control:8000 ETL_ADMIN_UPSTREAM=etl-stream:8000 ENGINE_ADMIN_UPSTREAM=narrative-live:8000 \
    ENABLE_DEV_ADMIN=0
# Substitute only deployment inputs, preserving native nginx variables.
ENV NGINX_ENVSUBST_FILTER="^(BACKEND_UPSTREAM|NGINX_RESOLVER|MEDIA_ORIGIN|FEED_ADMIN_UPSTREAM|DEMO_CONTROL_UPSTREAM|ETL_ADMIN_UPSTREAM|ENGINE_ADMIN_UPSTREAM|ENABLE_DEV_ADMIN)$"
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --chmod=755 tools/nginx-setup.envsh /docker-entrypoint.d/15-itg-setup.envsh
COPY --from=build /site/ /usr/share/nginx/html/
COPY assets/icons/ /usr/share/nginx/html/assets/icons/
COPY assets/league/ /usr/share/nginx/html/assets/league/
