docker rm -f aave-api 2>/dev/null || true

docker run \
    --name aave-api \
    -p 8000:8000 \
    -v ./config.yaml:/app/config.yaml:ro \
    aave-backend
