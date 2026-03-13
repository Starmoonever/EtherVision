docker rm aave-frontend 2>/dev/null || true

docker run \
    --name aave-frontend \
    -p 5173:5173 \
    aave-frontend
