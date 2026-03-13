FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY . .

EXPOSE 8000

# Mount config.yaml at runtime:
#   docker run -v ./config.yaml:/app/config.yaml ...
CMD ["uv", "run", "aave-api", "--host", "0.0.0.0", "--port", "8000"]
