# HospitalOS cockpit (React build served as static files) with reverse proxy to the two product APIs.
FROM node:22.12.0-bookworm-slim@sha256:35531c52ce27b6575d69755c73e65d4468dba93a25644eed56dc12879cae9213 AS build
WORKDIR /web
COPY web/package.json web/package-lock.json /web/
RUN npm ci
COPY web /web
RUN npm run build

FROM nginx:1.27.3-alpine@sha256:814a8e88df978ade80e584cc5b333144b9372a8e3c98872d07137dbf3b44d0e4
COPY infrastructure/cockpit/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /web/dist /usr/share/nginx/html
# Unprivileged port; the nginx master drops to the nginx user for workers.
EXPOSE 8080
