FROM node:24-alpine AS build
WORKDIR /frontend
COPY package.json package-lock.json .npmrc tsconfig.json ./
RUN npm ci --ignore-scripts
COPY match/ match/
COPY lab/ lab/
COPY tools/build.sh tools/vendor.sh tools/
RUN npm run build && sh tools/build.sh /site dist && cp -R dist/lab /site/lab

FROM nginx:1.28-alpine
ENV BACKEND_UPSTREAM=backend:8000 NGINX_RESOLVER=127.0.0.11
# Substitute only deployment inputs, preserving native nginx variables.
ENV NGINX_ENVSUBST_FILTER="^(BACKEND_UPSTREAM|NGINX_RESOLVER)$"
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /site/ /usr/share/nginx/html/
COPY assets/icons/ /usr/share/nginx/html/assets/icons/
COPY assets/league/ /usr/share/nginx/html/assets/league/
