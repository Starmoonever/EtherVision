# aave-crawler（后端）

以太主网 **Aave V3** 后端，提供三项功能：

1. **批量快照**（`crawl`）：从 PostgreSQL 读取所有用户地址，并发拉取链上仓位数据，持久化为可查询快照
2. **增量监听**（`watch`）：持续轮询链上历史事件，仅重爬有操作的用户，保持快照实时性
3. **REST API**：7 个 HTTP 端点，支持实时链上查询、历史仓位重建、价格区间查询与清算模拟

## 依赖

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.12+ | |
| [uv](https://docs.astral.sh/uv/) | 最新 | 包管理器 |
| PostgreSQL | 14+ | 需有 `loan.all_aave_eth_users` 表（含 `walletaddress` 列）及 `aave.aave_history` 历史表（来自 chain-data-collector） |

---

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
rpc_url: "http://your-rpc-node:port/"   # 留空则自动使用公共以太主网节点

postgres:
  host: "127.0.0.1"
  port: 5432
  user: "your_pg_user"
  password: "your_pg_password"
  database: "your_database"

crawler:
  concurrency: 20      # 并发用户数，建议 10~30
  batch_size: 100      # 每批写入 DB 的用户数
  rpc_timeout: 20      # 单次 RPC 超时（秒）
  retry_count: 3

watcher:
  interval: 60         # 轮询间隔（秒）
  lookback_minutes: 10 # 首次启动时回看多少分钟的历史事件
```

> `config.yaml` 已加入 `.gitignore`，不会提交到版本控制。

---

## CLI 命令

### `aave-crawler crawl` — 批量全量快照

首次运行会自动建表（`CREATE TABLE IF NOT EXISTS`），无需手动 DDL。

```bash
# 正式批量爬取（UPSERT 覆盖）
uv run aave-crawler crawl

# 仅处理前 10 个用户，不写入数据库（调试用）
uv run aave-crawler crawl --limit 10 --dry-run

# 指定配置文件
uv run aave-crawler crawl --config /path/to/config.yaml

# 输出 DEBUG 日志
uv run aave-crawler crawl --verbose
```

| 选项 | 说明 |
|------|------|
| `--config / -c` | 配置文件路径，默认自动查找 |
| `--limit / -n` | 仅处理前 N 个用户（调试用） |
| `--dry-run` | 只查询，不写入数据库 |
| `--verbose / -v` | 输出 DEBUG 日志 |

---

### `aave-crawler watch` — 增量监听（持续运行）

轮询 `aave.aave_history`，当检测到某用户有新的链上操作时，重新爬取该用户的仓位并更新快照。适合放在后台常驻运行。

```bash
# 使用 config.yaml 中的默认参数
uv run aave-crawler watch

# 每 30 秒轮询一次，首次回看 20 分钟内的事件
uv run aave-crawler watch --interval 30 --lookback 20

# 指定配置文件
uv run aave-crawler watch --config /path/to/config.yaml --verbose
```

| 选项 | 说明 |
|------|------|
| `--config / -c` | 配置文件路径 |
| `--interval / -i` | 轮询间隔（秒），覆盖 config.yaml 中的值 |
| `--lookback / -l` | 首次启动时回看多少分钟的历史事件 |
| `--verbose / -v` | 输出 DEBUG 日志 |

---

### `aave-crawler check` — 调试单个地址

```bash
uv run aave-crawler check 0xYourAddress
uv run aave-crawler check 0xYourAddress --verbose
```

---

## API 服务

### 启动

```bash
# 默认监听 0.0.0.0:8000
uv run aave-api

# 开发热重载
uv run aave-api --reload

# 自定义端口
uv run aave-api --port 8080

# 生产多进程
uv run aave-api --workers 4
```

启动后访问 `http://localhost:8000/docs` 查看交互式 Swagger 文档。

---

### 端点概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/user/position` | 查询单用户实时或历史仓位 |
| GET | `/api/user/liq_price` | 计算单用户 ETH 清算触发价 |
| GET | `/api/positions` | 批量仓位排行（实时快照或历史重建） |
| GET | `/api/price` | 查询资产价格（实时链上或 DeFiLlama 历史） |
| GET | `/api/price/period` | 查询资产在时间段内按分钟间隔的历史价格序列 |
| GET | `/api/liquidate` | 模拟指定 ETH 价格下的全网清算情况 |
| GET | `/api/liquidate/period` | 模拟 ETH 价格在区间内波动时清算量的变化趋势 |
| GET | `/health` | 服务健康检查 |

---

### `GET /api/user/position`

查询指定用户的 Aave V3 完整仓位。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `address` | string | ✅ | 以太坊钱包地址（支持校验和或小写） |
| `date` | string | ❌ | 历史时间点（UTC），如 `2024-11-14T12:00:00Z`、`2024-11-14`；省略则查询实时链上数据 |

**省略 `date`（实时）**，返回 `PositionResponse`：

```bash
curl "http://localhost:8000/api/user/position?address=0xYourAddress"
```

```json
{
  "address": "0xabc...",
  "eth_collateral_amount": "2.000000",
  "eth_collateral_usd": "5000.00",
  "total_debt_usd": "2000.00",
  "health_factor": "2.1250",
  "ltv": "0.4000",
  "liq_threshold": "0.8500",
  "liq_price": "1176.47"
}
```

**指定 `date`（历史重建）**，返回 `HistoricalPositionResponse`：

```bash
curl "http://localhost:8000/api/user/position?address=0xYourAddress&date=2024-11-14"
```

```json
{
  "address": "0xabc...",
  "at_time": "2024-11-14T00:00:00Z",
  "eth_collateral_amount": "1.850000",
  "eth_price_usd": "2350.00",
  "eth_collateral_usd": "4347.50",
  "total_debt_approx_usd": "1800.00",
  "liq_price": "1081.08",
  "reserves": [
    {
      "symbol": "WETH",
      "token_address": "0xC02aaA...",
      "supply_amount": "1.850000",
      "debt_amount": "0.000000"
    }
  ],
  "note": "供给量通过 scaled balance × liquidity_index 计算含利息，但不含最后一次操作到查询时间之间的利息累积"
}
```

> 若历史数据库中无该地址的操作记录，自动回退到实时链上数据，返回 `PositionResponse`。

---

### `GET /api/user/liq_price`

计算当 ETH 价格跌至多少时，该用户的健康系数将触碰 1.0。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `address` | string | ✅ | 以太坊钱包地址 |

```bash
curl "http://localhost:8000/api/user/liq_price?address=0xYourAddress"
```

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

`distance_pct`：当前价格距清算价的安全空间百分比（正数 = 安全，负数 = 已超过清算价）。

---

### `GET /api/positions`

批量查询仓位排行。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `orderby` | `liq_price` \| `health_factor` | `liq_price` | 排序字段（仅实时模式有效） |
| `order` | `asc` \| `desc` | `asc` | 排序方向（仅实时模式有效） |
| `limit` | int (1~200) | `10` | 返回记录数（历史模式最多 100） |
| `date` | string | — | 历史时间点；省略则查询数据库实时快照 |

**实时模式**（省略 `date`）：从数据库爬取快照中读取，返回 `list[PositionResponse]`。

```bash
# 清算价最高的 20 个账户（最危险）
curl "http://localhost:8000/api/positions?orderby=liq_price&order=desc&limit=20"
```

**历史模式**（指定 `date`）：从 `aave.aave_history` 重建，按 ETH 抵押量降序，返回 `list[HistoricalPositionResponse]`。

```bash
curl "http://localhost:8000/api/positions?date=2024-11-14&limit=50"
```

---

### `GET /api/price`

查询资产 USD 价格。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `asset` | string | `eth` | 资产名称，如 `eth`、`wbtc`、`usdc` |
| `time` | string | `now` | `now` = 实时链上价格；UTC 时间字符串 = DeFiLlama 历史价格 |

```bash
# 实时 ETH 价格
curl "http://localhost:8000/api/price?asset=eth"

# 历史 ETH 价格
curl "http://localhost:8000/api/price?asset=eth&time=2024-11-14T12:00:00Z"
```

```json
{
  "asset": "ETH",
  "price_usd": "2500.00",
  "token_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
  "timestamp": "2024-11-14T12:00:00Z",
  "source": "on-chain"
}
```

`source` 字段：`on-chain`（链上 Aave Oracle）或 `defillama`（DeFiLlama 历史接口）。

---

### `GET /api/price/period`

从 DeFiLlama 批量查询资产在指定时间段内，按固定分钟间隔的历史价格序列。仅发起一次 HTTP 请求后在内存中生成序列（并发逐点查询 DeFiLlama）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `asset` | string | `eth` | 资产名称，如 `eth`、`wbtc`、`usdc` |
| `start` | string | （必填） | 起始 UTC 时间，如 `2025-01-01T00:00:00Z`、`2025-01-01` |
| `end` | string | （必填） | 结束 UTC 时间（含），格式同上 |
| `interval` | int ≥ 1 | `60` | 采样间隔（分钟） |

支持时间格式：`2025-01-01T12:00:00Z` / `2025-01-01T12:00:00` / `2025-01-01 12:00:00` / `2025-01-01`

```bash
# 查询 ETH 在 2025-02-01 内每小时的价格
curl "http://localhost:8000/api/price/period?asset=eth&start=2025-02-01&end=2025-02-02&interval=60"

# USDT 每 30 分钟一个采样点
curl "http://localhost:8000/api/price/period?asset=usdt&start=2025-02-01&end=2025-02-01T06:00:00Z&interval=30"
```

```json
{
  "asset": "ETH",
  "token_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
  "source": "defillama",
  "prices": [
    { "price_usd": "2800.00", "timestamp": "2025-02-01T00:00:00Z" },
    { "price_usd": "2815.30", "timestamp": "2025-02-01T01:00:00Z" },
    { "price_usd": "2790.45", "timestamp": "2025-02-01T02:00:00Z" }
  ]
}
```

> 若 DeFiLlama 查询某采样点失败，该点 `price_usd` 设为 `"0.00"` 而非中断整个请求。

---

### `GET /api/liquidate`

模拟当 ETH 价格跌至指定值时，哪些账户将被触发清算，以及可供清算人获取的抵押品总额。

数据来源：数据库实时快照（需先运行 `aave-crawler crawl` 或 `watch`）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `eth_price` | float > 0 | （必填） | 模拟的 ETH 价格（USD） |
| `limit` | int (1~1000) | `100` | 返回的仓位数量上限；**不影响汇总统计**（统计基于全量触发仓位） |
| `orderby` | `liq_price` \| `eth_collateral_amount` \| `eth_collateral_usd` \| `total_debt_usd` | `liq_price` | 排序字段 |
| `order` | `desc` \| `asc` | `desc` | 排序方向 |

```bash
# 模拟 ETH 跌至 $2000，按抵押品 USD 降序，取前 10 条
curl "http://localhost:8000/api/liquidate?eth_price=2000&orderby=eth_collateral_usd&order=desc&limit=10"
```

```json
{
  "simulated_eth_price": "2000.00",
  "positions": [
    {
      "address": "0xabc...",
      "liq_price": "2150.00",
      "eth_collateral_amount": "10.000000",
      "eth_collateral_usd": "20000.00",
      "total_debt_usd": "18000.00"
    }
  ],
  "total_eth_collateral_amount": "354.123456",
  "total_eth_collateral_usd": "708246.91",
  "total_liquidation_usd": "650000.00",
  "note": "共 87 个仓位将在 ETH=$2000 时触发清算（本次返回前 10 条）；..."
}
```

**清算折价说明**：Aave V3 WETH 清算奖励系数为 1.05，即：

$$\text{total\_liquidation\_usd} = \sum \min\!\left(\text{debt} \times 1.05,\ \text{eth\_collateral\_usd}\right)$$

> `total_eth_collateral_usd` 及 `total_liquidation_usd` 始终基于**全部**触发仓位，不受 `limit` 影响。

---

### `GET /api/liquidate/period`

分析 ETH 价格在指定区间内以固定步长变化时，各价格点对应的清算量汇总。仅进行**一次**数据库查询，之后在内存中对每个价格点做过滤统计，效率较高。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `start` | float > 0 | （必填） | 起始 ETH 价格（USD） |
| `end` | float > 0 | （必填） | 结束 ETH 价格（USD），须 >= `start` |
| `interval` | float > 0 | （必填） | 价格步长（USD） |

```bash
# 分析 ETH 从 $500 跌至 $2000，每 $100 一个价格点的清算情况
curl "http://localhost:8000/api/liquidate/period?start=500&end=2000&interval=100" | jq .
```

```json
[
  {
    "simulated_eth_price": "500.00",
    "positions_cnt": "312",
    "total_eth_collateral_amount": "1840.230000",
    "total_eth_collateral_usd": "920115.00",
    "total_liquidation_usd": "880000.00"
  },
  {
    "simulated_eth_price": "600.00",
    "positions_cnt": "287",
    "total_eth_collateral_amount": "1650.100000",
    "total_eth_collateral_usd": "990060.00",
    "total_liquidation_usd": "850000.00"
  }
]
```

返回列表按价格**升序**排列（从 `start` 到 `end`），可直接用于绘制清算量随价格变化的折线图。

**清算折价说明**（同 `/api/liquidate`）：

$$\text{total\_liquidation\_usd} = \sum \min\!\left(\text{debt} \times 1.05,\ \text{eth\_collateral\_usd}\right)$$

---

### `GET /health`

```bash
curl "http://localhost:8000/health"
# {"status": "ok"}
```

---

## 数据库表结构

### `loan.aave_v3_eth_positions`（账户汇总快照）

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

### `loan.aave_v3_eth_reserve_positions`（逐资产明细快照）

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

写入策略：**全量 UPSERT**，每次爬取覆盖最新快照。

### `aave.aave_history`（链上历史事件，由 chain-data-collector 维护）

用于历史仓位重建，`address` / `token` 等字段以 bytea 存储 ASCII 文本，查询时使用 `convert_from(col, 'UTF8')`。

---

## 项目结构

```
backend/
├── pyproject.toml
├── config.yaml.example
├── config.yaml              # 本地配置（gitignored）
├── tests/
│   ├── conftest.py          # pytest fixtures & mock 数据
│   └── test_routes.py       # 138 个路由单元测试（全 mock，无需真实 DB/RPC）
└── aave_crawler/
    ├── cli.py               # Click CLI 入口（aave-crawler 命令）
    ├── server.py            # FastAPI app 工厂 + uvicorn 入口（aave-api 命令）
    ├── config.py            # 配置加载
    ├── models.py            # 数据模型（dataclass）
    ├── rpc.py               # 合约调用（web3.py AsyncWeb3）
    ├── db.py                # asyncpg：DDL + UPSERT
    ├── crawler.py           # 并发批量爬取主流程
    ├── watcher.py           # 增量监听主流程
    └── api/
        ├── schemas.py       # Pydantic 响应模型
        ├── service.py       # 业务逻辑（仓位查询、清算价计算、模拟清算、价格序列）
        └── routes.py        # FastAPI 路由（7 个端点）
```

---

## 开发

### 运行测试

```bash
uv run pytest tests/ -q
```

### 常用 uv 命令

```bash
# 添加运行时依赖
uv add some-package

# 添加开发依赖
uv add --dev some-package

# 在项目虚拟环境中运行任意脚本
uv run python your_script.py
```

### 合约地址（以太主网）

| 合约 | 地址 |
|------|------|
| Aave V3 Pool | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` |
| PoolDataProvider | `0x7B4EB56E7CD4b454BA8ff71E4518426369a138a3` |
| Aave Oracle | `0x54586bE62E3c3580375aE3723C145253060Ca0C2` |
