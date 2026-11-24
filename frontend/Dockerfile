# CareBridge AI frontend: build with Node, serve static files with unprivileged nginx. Build context: this folder.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` is strict. If package-lock.json predates a dependency in package.json (e.g. after pulling this update) fall back to `npm install`.
# Commit the regenerated lockfile and the fallback never triggers.
RUN npm ci || (echo 'package-lock.json is out of date: running npm install' && npm install)
COPY . .
# The browser calls /api on the same origin; nginx forwards it to the backend (see nginx.conf).
ARG VITE_API_URL=/api
ARG VITE_CONTACT_EMAIL=
# Public, browser-visible settings are compiled in at BUILD time (Vite). They are not secrets: restrict the Google key by HTTP referrer.
ARG VITE_GOOGLE_MAPS_API_KEY=
ARG VITE_GOOGLE_MAP_ID=
ARG VITE_CESIUM_VERSION=1.121
ARG VITE_SENTRY_DSN=
ARG VITE_SENTRY_ENVIRONMENT=production
ENV VITE_API_URL=$VITE_API_URL VITE_CONTACT_EMAIL=$VITE_CONTACT_EMAIL VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY VITE_GOOGLE_MAP_ID=$VITE_GOOGLE_MAP_ID \
    VITE_CESIUM_VERSION=$VITE_CESIUM_VERSION VITE_SENTRY_DSN=$VITE_SENTRY_DSN VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
