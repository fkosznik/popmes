FROM node:24-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM nginx:1.28-alpine
# nginx:1.28-alpine ships OpenSSL 3.5.5 (CVE-2026-31789) and brotli 1.2.0 (CVE-2026-111497).
RUN apk upgrade --no-cache libcrypto3 libssl3 brotli-libs
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
