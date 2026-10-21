# CareBridge AI frontend: build with Node, serve static files with unprivileged nginx. Build context: this folder.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The browser calls /api on the same origin; nginx forwards it to the backend (see nginx.conf).
ARG VITE_API_URL=/api
ARG VITE_CONTACT_EMAIL=
ENV VITE_API_URL=$VITE_API_URL VITE_CONTACT_EMAIL=$VITE_CONTACT_EMAIL
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
