# Admissions SMR web app, served by nginx with /api proxied to the API container.
#   docker build -f services/admissions_web/Dockerfile -t hospitalos/admissions-web .
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY services/admissions_web/package.json services/admissions_web/package-lock.json ./
RUN npm ci
COPY services/admissions_web ./
RUN npm run build

FROM nginx:1.27-alpine
COPY services/admissions_web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
