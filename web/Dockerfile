# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Frontend: Next.js (static export) → Nginx
#   Stage 1 build bằng Node, stage 2 chỉ còn file tĩnh + Nginx (reverse proxy /api → api:8000)
#   On-prem: override NODE_IMAGE / NGINX_IMAGE / NPM_REGISTRY bằng registry nội bộ.
# ---------------------------------------------------------------------------
ARG NODE_IMAGE=node:24-alpine
ARG NGINX_IMAGE=nginx:1.30-alpine

FROM ${NODE_IMAGE} AS build
ARG NPM_REGISTRY=https://registry.npmjs.org/
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry ${NPM_REGISTRY} && npm ci --no-audit --no-fund
COPY . .
RUN npm run build   # → /app/out

FROM ${NGINX_IMAGE}
ENV API_UPSTREAM=api:8000 \
    CLIENT_MAX_BODY_SIZE=60m
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/out /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/nginx-health || exit 1
