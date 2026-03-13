# ── Stage 1: Build ──────────────────────────────────────────────
FROM node:22-slim AS builder

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

WORKDIR /app

# Install deps first for layer caching
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build-time env vars (override when building the image)
#   docker build --build-arg VITE_API_BASE_URL=http://your-api:8000/api ...
ARG VITE_API_BASE_URL=http://localhost:8000/api
ARG VITE_RPC_URL=""

# config.yaml is read by vite.config.ts to inject VITE_RPC_URL
RUN printf 'rpc_url: "%s"\n' "${VITE_RPC_URL}" > config.yaml

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY . .
RUN pnpm run build

# ── Stage 2: Serve ───────────────────────────────────────────────
FROM nginx:alpine AS runner

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
