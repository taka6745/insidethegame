FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY lab/ /usr/share/nginx/html/lab/
COPY assets/icons/ /usr/share/nginx/html/assets/icons/
COPY assets/league/ /usr/share/nginx/html/assets/league/
COPY match/ /tmp/frontend/match/
COPY tools/build.sh /tmp/frontend/tools/build.sh
RUN sh /tmp/frontend/tools/build.sh /usr/share/nginx/html && rm -rf /tmp/frontend
