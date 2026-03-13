docker build \
    --build-arg VITE_API_BASE_URL=http://localhost:8000/api \
    --build-arg VITE_RPC_URL=http://10.8.6.153:2700/ \
    -t aave-frontend .
