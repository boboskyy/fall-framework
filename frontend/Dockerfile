# Static research console served by nginx, proxying /api → gateway.
# (Replaces the previous Next.js build; the dashboard is now a no-build static
#  app in the proj- design language.)
FROM nginx:alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY web /usr/share/nginx/html

EXPOSE 3000
HEALTHCHECK CMD wget --spider -q http://localhost:3000/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
