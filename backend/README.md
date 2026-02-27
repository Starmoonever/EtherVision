# aave-crawler（后端）

以太主网 Aave V3 后端，提供两项功能：

1. **批量爬取**：从 PostgreSQL 读取用户地址，并发查询链上 Aave 仓位，将结果持久化回库
2. **REST API**：提供给前端调用的 HTTP 接口，实时查询单个用户仓位及 ETH liq_price

## 依赖

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（包管理器）
- PostgreSQL（已有 `loan.all_aave_eth_users` 表，含 `walletaddress` 列）

## 快速开始

### 1. 安装依赖

```bash
cd backend
uv sync
```

### 2. 配置

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml`：

```yaml
rpc_url: "http://your-rpc-node:port/"   # 留空则自动使用公共 Base 节点

postgres:
  host: "127.0.0.1"
  port: 5432
  user: "your_pg_user"
  password: "your_pg_password"
  database: "your_database"

crawler:
  concurrency: 20    # 并发用户数，建议 10~30
  batch_size: 100    # 每次写入 DB 的用户数
  rpc_timeout: 20    # 单次 RPC 超时（秒）
  retry_count: 3
```

> `config.yaml` 已加入 `.gitignore`，不会提交到版本控制。

### 3. 建表 & 运行

首次运行会自动创建目标表（`CREATE TABLE IF NOT EXISTS`），无需手动建表：

```bash
# 正式批量爬取
uv run aave-crawler crawl

# 仅处理前 10 个用户（调试用，不写 DB）
uv run aave-crawler crawl --limit 10 --dry-run

# 指定配置文件路径
uv run aave-crawler crawl --config /path/to/config.yaml
```

### 4. 调试单个地址

```bash
uv run aave-crawler check 0xYourAddress
uv run aave-crawler check 0xYourAddress --verbose
```

## API 服务

### 启动

```bash
# 默认监听 0.0.0.0:8000
uv run aave-api

# 自定义端口，开发热重载
uv run aave-api --port 8080 --reload

# 生产多进程
uv run aave-api --workers 4
```

启动后自动连接 `config.yaml` 中配置的 RPC 节点。

### 接口文档

服务启动后访问 `http://localhost:8000/docs` 查看交互式 Swagger 文档。

### 端点

#### `GET /api/user/position?address=`

实时从链上查询用户的 Aave V3 完整仓位。

```bash
curl "http://localhost:8000/api/user/position?address=0xYourAddress"
```

响应示例：
```json
{
  "address": "0xabc...",
  "block_number": 21900000,
  "summary": {
    "total_collateral_usd": "5000.00",
    "total_debt_usd": "2000.00",
    "health_factor": "2.1250",
    "ltv": "0.4000",
    "liq_threshold": "0.8500"
  },
  "reserves": [
    {
      "symbol": "WETH",
      "price_usd": "2500.00",
      "supply_amount": "2.000000",
      "supply_usd": "5000.00",
      "variable_debt_amount": "0.800000",
      "total_debt_usd": "2000.00",
      "use_as_collateral": true
    }
  ]
}
```

#### `GET /api/user/liq_price?address=`

计算 ETH 价格跌至多少时触发清算风险（HF → 1.0）。

```bash
curl "http://localhost:8000/api/user/liq_price?address=0xYourAddress"
```

响应示例：
```json
{
  "address": "0xabc...",
  "current_eth_price_usd": "2500.00",
  "liquidation_eth_price_usd": "1176.47",
  "distance_pct": "52.94",
  "health_factor": "2.1250",
  "note": ""
}
```

`distance_pct`：当前价格距清算价的安全空间百分比（正数 = 安全）。

#### `GET /health`

服务健康检查，返回 `{"status": "ok"}`。

## 目标表结构

### `loan.aave_v3_eth_positions`（账户汇总）

| 列 | 类型 | 说明 |
|---|---|---|
| `user_address` | TEXT PK | 小写钱包地址 |
| `block_number` | BIGINT | 查询时区块号 |
| `scanned_at` | TIMESTAMPTZ | 查询时间（UTC） |
| `total_collateral_usd` | NUMERIC(20,8) | 总抵押物 USD |
| `total_debt_usd` | NUMERIC(20,8) | 总借贷 USD |
| `available_borrows_usd` | NUMERIC(20,8) | 可借额度 USD |
| `health_factor` | NUMERIC(30,18) | 健康系数，∞ 时存 `1e18` |
| `ltv` | NUMERIC(8,4) | 贷款价值比（0~1） |
| `liq_threshold` | NUMERIC(8,4) | 清算阈值（0~1） |

### `loan.aave_v3_eth_reserve_positions`（逐资产明细）

| 列 | 类型 | 说明 |
|---|---|---|
| `user_address` + `token_address` | PK | 联合主键 |
| `symbol` | TEXT | 资产符号（如 WETH） |
| `block_number` / `scanned_at` | — | 同汇总表 |
| `decimals` | INTEGER | 代币精度 |
| `price_usd` | NUMERIC(20,8) | Oracle 价格 |
| `supply_raw` | NUMERIC(40,0) | 链上原始供给整数 |
| `supply_usd` | NUMERIC(20,8) | 供给 USD 估值 |
| `stable_debt_raw` / `variable_debt_raw` | NUMERIC(40,0) | 链上原始借贷整数 |
| `total_debt_usd` | NUMERIC(20,8) | 借贷 USD 估值 |
| `use_as_collateral` | BOOLEAN | 是否用作抵押品 |

写入策略：**UPSERT 覆盖**（每次爬取覆盖最新快照）。

## 项目结构

```
backend/
├── pyproject.toml
├── config.yaml.example
├── config.yaml              # 本地配置（gitignored）
└── aave_crawler/
    ├── cli.py               # Click CLI 入口（aave-crawler 命令）
    ├── server.py            # FastAPI app 工厂 + uvicorn 入口（aave-api 命令）
    ├── config.py            # 配置加载
    ├── models.py            # 数据模型（dataclass）
    ├── rpc.py               # 合约调用（web3.py AsyncWeb3）
    ├── db.py                # asyncpg，DDL + UPSERT
    ├── crawler.py           # 并发批量爬取主流程
    └── api/
        ├── schemas.py       # Pydantic 响应模型
        ├── service.py       # 业务逻辑（仓位查询、清算价计算）
        └── routes.py        # FastAPI 路由
```

## 常用 uv 命令

```bash
# 添加依赖
uv add some-package

# 添加开发依赖
uv add --dev some-package

# 运行任意脚本（使用项目虚拟环境）
uv run python your_script.py
```
