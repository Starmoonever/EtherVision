# aave-crawler（后端）

以太主网 **Aave V2 / V3** 后端，提供四项功能：

1. **地址同步**（`sync-addresses`）：从本地链上历史事件表（`aave.aave_history`）派生用户地址，写入来源表，替代 subgraph 外部依赖
2. **批量快照**（`crawl`）：从来源表读取所有用户地址，并发拉取链上仓位数据，持久化为可查询快照
3. **增量监听**（`watch`）：持续轮询链上历史事件，仅重爬有操作的用户，保持快照实时性
4. **REST API**：支持实时链上查询、历史仓位重建、价格区间查询与清算模拟，覆盖多头（抵押 ETH）和空头（借入 WETH）两个方向

---

## 架构设计

### 数据库访问模式（Dual-Access Pattern）

本项目采用 **双数据库访问模式**，在性能和类型安全之间取得平衡：

#### 1. SQLAlchemy AsyncSession（推荐用于 API 查询）

- **用途**：API 层的读操作（`api/routes.py` 和 `api/service.py`）
- **优势**：
  - 类型安全：ORM 模型提供完整类型提示
  - 迁移管理：Alembic 自动生成和追踪 schema 变更
  - 可维护性：声明式模型清晰表达数据结构
- **依赖注入**：通过 `DbSession = Annotated[AsyncSession, Depends(get_db)]` 注入路由

#### 2. asyncpg Pool（用于高性能场景）

- **用途**：
  - 批量写入（`crawler.py`：`COPY` 协议批量插入仓位数据）
  - 复杂事务（`get_borrow_user_position`：单连接多查询）
  - 性能关键路径（`simulate_liquidation_period`：单次查询 + 内存计算）
- **优势**：
  - 原生 PostgreSQL `COPY` 支持（比 ORM 快 10-50 倍）
  - 精细连接池控制（`pool.acquire()` 显式事务边界）
- **依赖注入**：通过 `AsyncpgPool = Annotated[asyncpg.Pool, Depends(get_pool)]` 注入路由

#### 何时使用哪种方式？

| 场景               | 推荐方式     | 原因                  |
| ------------------ | ------------ | --------------------- |
| API Single SELECT  | AsyncSession | 类型安全，代码简洁    |
| 批量 INSERT/UPDATE | asyncpg      | `COPY` 协议性能       |
| 多表 JOIN 查询     | AsyncSession | ORM relationship 导航 |
| 历史回放/缓存逻辑  | asyncpg      | 显式事务控制          |

### 数据库迁移（Alembic）

#### 初次设置（针对已有数据库）

如果数据库已有 `loan` schema 和所有表（通过 `db.py` 创建），需要标记当前状态为初始迁移：

```bash
cd backend
# 标记数据库已处于初始迁移状态（不执行实际迁移）
uv run alembic stamp head
```

#### 日常开发流程

1. **修改 ORM 模型**：编辑 `aave_crawler/orm_models.py`
2. **生成迁移脚本**：

   ```bash
   uv run alembic revision --autogenerate -m "描述变更内容"
   ```

3. **审查生成的迁移文件**：检查 `alembic/versions/xxxx_描述.py`
4. **应用迁移**：

   ```bash
   uv run alembic upgrade head
   ```

5. **回滚迁移**（如需）：

   ```bash
   uv run alembic downgrade -1  # 回退一个版本
   ```

#### 迁移注意事项

- **ORM 模型仅覆盖 `loan` schema**：其他 schema 的表（如 `aave_history`）不在 ORM 管理范围内
- **Autogenerate 不是完美的**：始终审查生成的迁移，手动调整复杂变更
- **团队协作**：提交前运行 `uv run alembic upgrade head` 验证迁移可执行

---

## 依赖

| 组件                             | 版本要求 | 说明                                                            |
| -------------------------------- | -------- | --------------------------------------------------------------- |
| Python                           | 3.12+    |                                                                 |
| [uv](https://docs.astral.sh/uv/) | 最新     | 包管理器                                                        |
| PostgreSQL                       | 14+      | 需有 `aave.aave_history` 历史表（由 chain-data-collector 维护） |
| SQLAlchemy                       | 2.0+     | 异步 ORM（已含在依赖中）                                        |
| Alembic                          | 1.13+    | 数据库迁移工具（已含在依赖中）                                  |

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
rpc_url: 'http://your-rpc-node:port/' # 留空则自动使用公共以太主网节点

postgres:
  host: '127.0.0.1'
  port: 5432
  user: 'your_pg_user'
  password: 'your_pg_password'
  database: 'your_database'

crawler:
  concurrency: 20 # 并发用户数，建议 10~30
  batch_size: 100 # 每批写入 DB 的用户数
  rpc_timeout: 20 # 单次 RPC 超时（秒）
  retry_count: 3

watcher:
  interval: 60 # 轮询间隔（秒）
  lookback_minutes: 10 # 首次启动时回看多少分钟的历史事件
```

> `config.yaml` 已加入 `.gitignore`，不会提交到版本控制。

---

## CLI 命令

### `aave-crawler sync-addresses` — 从历史事件派生用户地址

从 `aave.aave_history` 按协议版本（v2/v3）和操作类型（deposit/borrow）查询所有历史用户，写入 `loan` schema 的来源表。这是正式爬取前的必要步骤，也是替代 subgraph 的核心操作。

**数据特点**：包含历史上所有操作过 ETH 系资产的用户，含已还清仓位；RPC 爬取时会自动过滤无效仓位（`liq_price = 0` 或 `liq_price_rise = 0`）。

```bash
# 同步全部 4 张来源表（推荐首次使用）
uv run aave-crawler sync-addresses

# 仅同步 v3 借款地址
uv run aave-crawler sync-addresses -p v3_borrow

# 预览，不写入数据库
uv run aave-crawler sync-addresses --dry-run

# 使用 DEBUG 日志查看前 10 条预览
uv run aave-crawler sync-addresses --dry-run --verbose
```

**来源表**（自动建表，已存在则 UPSERT）：

| 来源表（`loan` schema）       | 内容                     |
| ----------------------------- | ------------------------ |
| `aave_v2_eth_weth_collateral` | v2 存入 ETH 系资产的用户 |
| `aave_v3_eth_weth_collateral` | v3 存入 ETH 系资产的用户 |
| `aave_v2_eth_weth_borrow`     | v2 借出 ETH 系资产的用户 |
| `aave_v3_eth_weth_borrow`     | v3 借出 ETH 系资产的用户 |

| 选项              | 说明                                                                     |
| ----------------- | ------------------------------------------------------------------------ |
| `--config / -c`   | 配置文件路径                                                             |
| `--protocol / -p` | 指定单张表：`v2` / `v3` / `v2_borrow` / `v3_borrow`；省略则同步全部 4 张 |
| `--dry-run`       | 只查询并预览，不写入数据库                                               |
| `--verbose / -v`  | 输出 DEBUG 日志                                                          |

---

### `aave-crawler crawl` — 批量全量快照

从来源表读取用户地址，并发调用链上 RPC，将仓位数据 UPSERT 到目标快照表。首次运行会自动建表（`CREATE TABLE IF NOT EXISTS`），无需手动 DDL。

```bash
# v3 抵押端全量覆写
uv run aave-crawler crawl

# v2 抵押端全量覆写
uv run aave-crawler crawl -p v2

# v3 借贷端（借入 WETH）全量覆写
uv run aave-crawler crawl -p v3_borrow

# v2 借贷端增量（跳过已爬地址）
uv run aave-crawler crawl -p v2_borrow --incremental

# 仅处理前 10 个用户，不写入数据库（调试用）
uv run aave-crawler crawl --limit 10 --dry-run
```

| 选项                 | 说明                                               |
| -------------------- | -------------------------------------------------- |
| `--config / -c`      | 配置文件路径，默认自动查找                         |
| `--protocol / -p`    | `v2` / `v3`（默认） / `v2_borrow` / `v3_borrow`    |
| `--source / -s`      | 地址来源协议版本（如从 v2 地址列表爬 v3 仓位）     |
| `--limit / -n`       | 仅处理前 N 个用户（调试用）                        |
| `--dry-run`          | 只查询，不写入数据库                               |
| `--incremental / -i` | 增量模式：跳过目标表中已存在的地址，仅处理新增地址 |
| `--verbose / -v`     | 输出 DEBUG 日志                                    |

---

### `aave-crawler watch` — 增量监听（持续运行）

轮询 `aave.aave_history`，检测到用户有新链上操作时重爬并更新快照。适合放在后台常驻运行。

```bash
# v3 抵押端监听（使用 config.yaml 默认参数）
uv run aave-crawler watch

# v3 借贷端监听，30 秒轮询，首次回看 60 分钟
uv run aave-crawler watch -p v3_borrow --interval 30 --lookback 60

# 后台运行并写入日志
nohup uv run aave-crawler watch -p v3_borrow -l 60 > nohup_v3_borrow.log 2>&1 &
```

| 选项              | 说明                                            |
| ----------------- | ----------------------------------------------- |
| `--config / -c`   | 配置文件路径                                    |
| `--protocol / -p` | `v2` / `v3`（默认） / `v2_borrow` / `v3_borrow` |
| `--interval / -i` | 轮询间隔（秒），覆盖 config.yaml 中的值         |
| `--lookback / -l` | 首次启动时回看多少分钟的历史事件                |
| `--verbose / -v`  | 输出 DEBUG 日志                                 |

---

### `aave-crawler check` — 调试单个地址

```bash
uv run aave-crawler check 0xYourAddress
uv run aave-crawler check 0xYourAddress --verbose
```

---

### 典型工作流

```bash
# 1. 首次：从历史事件派生所有用户地址
uv run aave-crawler sync-addresses

# 2. 全量爬取四个维度的仓位快照
uv run aave-crawler crawl -p v2
uv run aave-crawler crawl -p v3
uv run aave-crawler crawl -p v2_borrow
uv run aave-crawler crawl -p v3_borrow

# 3. 后台启动增量监听（保持实时性）
nohup uv run aave-crawler watch -p v3        > nohup_v3.log 2>&1 &
nohup uv run aave-crawler watch -p v3_borrow > nohup_v3_borrow.log 2>&1 &

# 4. 启动 API
uv run aave-api
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

#### 抵押端（ETH 下跌风险 / `collateral`）

| 方法 | 路径                    | 说明                                                                |
| ---- | ----------------------- | ------------------------------------------------------------------- |
| GET  | `/api/position`         | 查询单用户实时或历史仓位                                            |
| GET  | `/api/liq_price`        | 计算单用户 ETH 下跌清算触发价                                       |
| GET  | `/api/positions`        | 批量仓位排行（实时快照或历史重建）；仅含 `liq_price > 0` 的有效仓位 |
| GET  | `/api/position/replay`  | 以 transaction 为数据点回放指定地址历史仓位（支持缓存）             |
| GET  | `/api/txs`              | 查询指定地址在时间范围内的 Aave 历史交易列表                        |
| GET  | `/api/price`            | 查询资产价格（实时链上或 DeFiLlama 历史）                           |
| GET  | `/api/price/period`     | 查询资产在时间段内按分钟间隔的历史价格序列                          |
| GET  | `/api/liquidate`        | 模拟 ETH 价格下跌时的全网清算情况                                   |
| GET  | `/api/liquidate/period` | 模拟 ETH 价格在区间内波动时清算量的变化趋势                         |

#### 借贷端（ETH 上涨风险 / `borrow`）

| 方法 | 路径                           | 说明                                                           |
| ---- | ------------------------------ | -------------------------------------------------------------- |
| GET  | `/api/borrow/positions`        | 查询借入 WETH 的仓位排行；仅含 `liq_price_rise > 0` 的有效仓位 |
| GET  | `/api/borrow/position`         | 查询单地址借贷端仓位详情                                       |
| GET  | `/api/borrow/liquidate`        | 模拟 ETH 价格上涨时的做空清算情况                              |
| GET  | `/api/borrow/liquidate/period` | 模拟 ETH 价格在区间内上涨时空头清算量的变化趋势                |

#### 通用

| 方法 | 路径      | 说明         |
| ---- | --------- | ------------ |
| GET  | `/health` | 服务健康检查 |

---

### `GET /api/position`

查询指定用户的 Aave 完整仓位。

| 参数      | 类型   | 必填 | 说明                                                                               |
| --------- | ------ | ---- | ---------------------------------------------------------------------------------- |
| `address` | string | ✅   | 以太坊钱包地址（支持校验和或小写）                                                 |
| `date`    | string | ❌   | 历史时间点（UTC），如 `2024-11-14T12:00:00Z`、`2024-11-14`；省略则查询实时链上数据 |
| `version` | string | ❌   | `v2` 或 `v3`（默认）                                                               |

**省略 `date`（实时）**，返回 `PositionResponse`：

```bash
curl "http://localhost:8000/api/position?address=0xYourAddress"
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
curl "http://localhost:8000/api/position?address=0xYourAddress&date=2024-11-14"
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

### `GET /api/liq_price`

计算当 ETH 价格跌至多少时，该用户的健康系数将触碰 1.0。

| 参数      | 类型   | 必填 | 说明                 |
| --------- | ------ | ---- | -------------------- |
| `address` | string | ✅   | 以太坊钱包地址       |
| `version` | string | ❌   | `v2` 或 `v3`（默认） |

```bash
curl "http://localhost:8000/api/liq_price?address=0xYourAddress"
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

批量查询抵押端仓位排行。**仅返回 `liq_price > 0` 的有效仓位**（有债务且有 ETH 系抵押品）。

| 参数      | 类型                                                                                                  | 默认值      | 说明                                 |
| --------- | ----------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------ |
| `orderby` | `liq_price` \| `health_factor` \| `eth_collateral_amount` \| `eth_collateral_usd` \| `total_debt_usd` | `liq_price` | 排序字段（仅实时模式有效）           |
| `order`   | `asc` \| `desc`                                                                                       | `asc`       | 排序方向                             |
| `limit`   | int (1~200)                                                                                           | `10`        | 返回记录数（历史模式最多 100）       |
| `date`    | string                                                                                                | —           | 历史时间点；省略则查询数据库实时快照 |
| `version` | string                                                                                                | `v3`        | `v2` 或 `v3`                         |

```bash
# 清算价最高的 20 个账户（最危险）
curl "http://localhost:8000/api/positions?orderby=liq_price&order=desc&limit=20"
```

---

### `GET /api/position/replay`

以 transaction 为数据点，回放指定地址在时间范围内**每笔 Aave 操作时刻的链上真实仓位**。

- 底层通过 `eth_call(block_identifier=N)` 直接读取历史链上状态，**无利息重建误差**
- 首次查询触发并发 RPC 重放（每批最多 5 个），结果写入 `loan.position_snapshot_cache`；缓存命中后直接返回，响应毫秒级
- 参数 `detail=true` 可展开每个数据点的资产明细（token 级别的供给量、借贷量、Oracle 价格）

| 参数        | 类型   | 必填 | 默认    | 说明                                                           |
| ----------- | ------ | ---- | ------- | -------------------------------------------------------------- |
| `address`   | string | ✅   | —       | 以太坊钱包地址                                                 |
| `start`     | string | ✅   | —       | 起始时间（UTC），如 `2024-01-01` / `2024-11-14T12:00:00Z`      |
| `end`       | string | ✅   | —       | 结束时间（UTC）                                                |
| `version`   | string | ❌   | `v3`    | `v2` 或 `v3`                                                   |
| `use_cache` | bool   | ❌   | `true`  | 是否优先读取缓存；设为 `false` 强制全量 RPC 重新查询并刷新缓存 |
| `detail`    | bool   | ❌   | `false` | `true` 时每个数据点附带 `reserves` 资产明细数组                |

```bash
curl "http://localhost:8000/api/position/replay?address=0xYourAddress&start=2024-11-01&end=2025-01-01&version=v3&detail=true"
```

```json
{
  "address": "0xabc...",
  "protocol": "v3",
  "from_time": "2024-11-01T00:00:00Z",
  "to_time": "2025-01-01T00:00:00Z",
  "data_source": "rpc",
  "total_points": 3,
  "cache_hit_rate": "0.00",
  "points": [
    {
      "tx_hash": "0xe005...",
      "block_number": 21281734,
      "timestamp": "2024-11-27T21:21:47Z",
      "eth_price_usd": "3633.92",
      "total_collateral_usd": "140461.55",
      "total_debt_usd": "83580.16",
      "available_borrows_usd": "0.00",
      "health_factor": "1.4266",
      "liq_threshold": "0.8250",
      "liq_price": "2470.00",
      "reserves": [
        {
          "symbol": "WETH",
          "token_address": "0xC02aaA...",
          "price_usd": "3633.92",
          "supply_usd": "140461.55",
          "total_debt_usd": "83580.16",
          "use_as_collateral": true
        }
      ]
    }
  ]
}
```

| 响应字段         | 说明                                                    |
| ---------------- | ------------------------------------------------------- |
| `data_source`    | `cache`（全命中）/ `rpc`（全重放）/ `mixed`（混合）     |
| `cache_hit_rate` | 缓存命中比例（`0.00`~`1.00`）                           |
| `liq_price`      | 该区块时刻 ETH 下跌清算触发价（USD）；`0` 表示无风险    |
| `health_factor`  | 健康系数；无借贷时为 `"inf"`                            |
| `reserves`       | 仅 `detail=true` 时填充；含 Oracle 价格、供给量、借贷量 |

---

### `GET /api/txs`

列出指定地址在时间范围内所有触发 Aave 仓位变化的历史交易。数据来源：`aave.aave_history` 表。每条记录附带 `cached` 字段，标注该 tx 的仓位快照是否已在 `/api/position/replay` 的缓存中。

| 参数      | 类型   | 必填 | 默认 | 说明            |
| --------- | ------ | ---- | ---- | --------------- |
| `address` | string | ✅   | —    | 以太坊钱包地址  |
| `start`   | string | ✅   | —    | 起始时间（UTC） |
| `end`     | string | ✅   | —    | 结束时间（UTC） |
| `version` | string | ❌   | `v3` | `v2` 或 `v3`    |

```bash
curl "http://localhost:8000/api/txs?address=0xYourAddress&start=2024-11-01&end=2025-01-01&version=v3"
```

```json
{
  "address": "0xabc...",
  "protocol": "v3",
  "from_time": "2024-11-01T00:00:00Z",
  "to_time": "2025-01-01T00:00:00Z",
  "total": 3,
  "txs": [
    {
      "tx_hash": "0xe005...",
      "block_number": 21281734,
      "timestamp": "2024-11-27T21:21:47Z",
      "operation_type": "borrow",
      "token_symbol": "WETH",
      "cached": false
    },
    {
      "tx_hash": "0x118f...",
      "block_number": 21290022,
      "timestamp": "2024-11-29T01:17:59Z",
      "operation_type": "repay",
      "token_symbol": "WETH",
      "cached": false
    }
  ]
}
```

`operation_type` 取值：`deposit` / `withdraw` / `borrow` / `repay` / `liquidationcall`。

---

### `GET /api/liquidate`

模拟当 ETH 价格跌至指定值时，有哪些账户将被触发清算，以及可供清算人获取的抵押品总额。

| 参数        | 类型                                                                               | 默认值      | 说明                                               |
| ----------- | ---------------------------------------------------------------------------------- | ----------- | -------------------------------------------------- |
| `eth_price` | float > 0                                                                          | （必填）    | 模拟的 ETH 价格（USD）                             |
| `limit`     | int (1~1000)                                                                       | `100`       | 返回仓位数；**不影响汇总统计**（统计基于全量触发） |
| `orderby`   | `liq_price` \| `eth_collateral_amount` \| `eth_collateral_usd` \| `total_debt_usd` | `liq_price` | 排序字段                                           |
| `order`     | `desc` \| `asc`                                                                    | `desc`      | 排序方向                                           |
| `eth_ratio` | float [0,1]                                                                        | 配置默认值  | ETH 抵押品占比最小阈值                             |
| `cap`       | float > 0                                                                          | —           | `liq_price` 上限（仅返回低于此价格的仓位）         |
| `version`   | string                                                                             | `v3`        | `v2` 或 `v3`                                       |

```bash
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
  "positions_cnt": "87",
  "total_eth_collateral_amount": "354.123456",
  "total_eth_collateral_usd": "708246.91",
  "total_liquidation_usd": "650000.00",
  "note": "..."
}
```

**清算折价说明**（Aave V3 WETH 清算奖励系数 1.05）：

$$\text{total\_liquidation\_usd} = \sum \min\!\left(\text{debt} \times 1.05,\ \text{eth\_collateral\_usd}\right)$$

---

### `GET /api/liquidate/period`

分析 ETH 价格在指定区间内以固定步长变化时，各价格点对应的清算量汇总。一次数据库查询，内存过滤，效率较高。

| 参数        | 类型      | 默认值   | 说明                                |
| ----------- | --------- | -------- | ----------------------------------- |
| `start`     | float > 0 | （必填） | 起始 ETH 价格（USD）                |
| `end`       | float > 0 | （必填） | 结束 ETH 价格（USD），须 >= `start` |
| `interval`  | float > 0 | （必填） | 价格步长（USD）                     |
| `eth_ratio` | float     |          | ETH 抵押品占比过滤                  |
| `version`   | string    | `v3`     | `v2` 或 `v3`                        |

```bash
curl "http://localhost:8000/api/liquidate/period?start=500&end=2000&interval=100" | jq .
```

返回按价格升序排列，可直接用于绘制清算量随价格变化的折线图。

---

### `GET /api/price`

| 参数    | 类型   | 默认值 | 说明                                                      |
| ------- | ------ | ------ | --------------------------------------------------------- |
| `asset` | string | `eth`  | 资产名称，如 `eth`、`wbtc`、`usdc`                        |
| `time`  | string | `now`  | `now` = 实时链上价格；UTC 时间字符串 = DeFiLlama 历史价格 |

```bash
curl "http://localhost:8000/api/price?asset=eth"
curl "http://localhost:8000/api/price?asset=eth&time=2024-11-14T12:00:00Z"
```

---

### `GET /api/price/period`

从 DeFiLlama 批量查询资产历史价格序列。

| 参数       | 类型    | 默认值   | 说明                           |
| ---------- | ------- | -------- | ------------------------------ |
| `asset`    | string  | `eth`    | 资产名称                       |
| `start`    | string  | （必填） | 起始 UTC 时间，如 `2025-01-01` |
| `end`      | string  | （必填） | 结束 UTC 时间（含）            |
| `interval` | int ≥ 1 | `60`     | 采样间隔（分钟）               |

```bash
curl "http://localhost:8000/api/price/period?asset=eth&start=2025-02-01&end=2025-02-02&interval=60"
```

---

### `GET /api/borrow/positions`

查询借入 WETH 的仓位排行。**仅返回 `liq_price_rise > 0` 的有效仓位**（面临 ETH 上涨清算风险）。

| 参数      | 类型                                                                       | 默认值           | 说明         |
| --------- | -------------------------------------------------------------------------- | ---------------- | ------------ |
| `orderby` | `liq_price_rise` \| `weth_debt_usd` \| `total_debt_usd` \| `health_factor` | `liq_price_rise` | 排序字段     |
| `order`   | `asc` \| `desc`                                                            | `asc`            | 排序方向     |
| `limit`   | int (1~200)                                                                | `10`             | 返回数量     |
| `version` | string                                                                     | `v3`             | `v2` 或 `v3` |

```bash
curl "http://localhost:8000/api/borrow/positions?orderby=liq_price_rise&order=asc&limit=20"
```

---

### `GET /api/borrow/position`

从数据库快照中读取单地址借贷端仓位（借入 WETH 场景），含汇总信息及每个资产的 reserve 明细。

| 参数      | 类型   | 必填 | 说明           |
| --------- | ------ | ---- | -------------- |
| `address` | string | ✅   | 以太坊钱包地址 |
| `version` | string | ❌   | `v2` 或 `v3`   |

地址不存在时返回 404。

---

### `GET /api/borrow/liquidate`

模拟当 ETH 价格涨至指定值时，有哪些借入 WETH 的账户会被清算。

| 参数        | 类型                                                    | 默认值           | 说明                      |
| ----------- | ------------------------------------------------------- | ---------------- | ------------------------- |
| `eth_price` | float > 0                                               | （必填）         | 模拟的 ETH 价格（USD）    |
| `limit`     | int (1~1000)                                            | `100`            | 返回仓位数                |
| `orderby`   | `liq_price_rise` \| `weth_debt_usd` \| `total_debt_usd` | `liq_price_rise` | 排序字段                  |
| `order`     | `asc` \| `desc`                                         | `asc`            | 排序方向                  |
| `cap`       | float > 0                                               | —                | `liq_price_rise` 上限     |
| `eth_ratio` | float [0,1]                                             | 配置默认值       | WETH 债务占总债务最小比例 |
| `version`   | string                                                  | `v3`             | `v2` 或 `v3`              |

**清算折价说明**：`total_liquidation_usd = Σ min(WETH债务USD × 1.05, 总抵押USD)`

---

### `GET /api/borrow/liquidate/period`

分析 ETH 价格在指定区间内上涨时，空头仓位清算量的变化趋势。

| 参数        | 类型      | 默认值   | 说明              |
| ----------- | --------- | -------- | ----------------- |
| `start`     | float > 0 | （必填） | 起始价格（USD）   |
| `end`       | float > 0 | （必填） | 结束价格（USD）   |
| `interval`  | float > 0 | （必填） | 步长（USD）       |
| `eth_ratio` | float     |          | WETH 债务占比过滤 |
| `version`   | string    | `v3`     | `v2` 或 `v3`      |

---

## 数据库表结构

### 抵押端仓位表（`loan.aave_{v2|v3}_eth_positions_collateral`）

| 列                      | 类型           | 说明                                  |
| ----------------------- | -------------- | ------------------------------------- |
| `user_address`          | TEXT PK        | 小写钱包地址                          |
| `block_number`          | BIGINT         | 查询时区块号                          |
| `scanned_at`            | TIMESTAMPTZ    | 查询时间（UTC）                       |
| `total_collateral_usd`  | NUMERIC(30,8)  | 总抵押物 USD                          |
| `total_debt_usd`        | NUMERIC(30,8)  | 总借贷 USD                            |
| `available_borrows_usd` | NUMERIC(30,8)  | 可借额度 USD                          |
| `health_factor`         | NUMERIC(40,18) | 健康系数，∞ 时存 `1e18`               |
| `ltv`                   | NUMERIC(8,4)   | 贷款价值比（0~1）                     |
| `liq_threshold`         | NUMERIC(8,4)   | 清算阈值（0~1）                       |
| `liq_price`             | NUMERIC(30,8)  | ETH 下跌清算触发价（USD）；0 = 无风险 |

### 借贷端仓位表（`loan.aave_{v2|v3}_eth_positions_borrow`）

在抵押端字段基础上额外包含：

| 列               | 类型          | 说明                                      |
| ---------------- | ------------- | ----------------------------------------- |
| `weth_debt_raw`  | NUMERIC(40,0) | ETH 系负债合计（原始 wei）                |
| `weth_debt_usd`  | NUMERIC(30,8) | ETH 系负债合计 USD（扫描时刻价格）        |
| `liq_price_rise` | NUMERIC(30,8) | ETH 上涨清算触发价（USD）；0 = 无上涨风险 |

### 资产明细表（`loan.aave_{v2|v3}_eth_reserve_positions_{collateral|borrow}`）

| 列                                      | 类型          | 说明                |
| --------------------------------------- | ------------- | ------------------- |
| `user_address` + `token_address`        | PK            | 联合主键            |
| `symbol`                                | TEXT          | 资产符号（如 WETH） |
| `block_number` / `scanned_at`           | —             | 同汇总表            |
| `decimals`                              | INTEGER       | 代币精度            |
| `price_usd`                             | NUMERIC(30,8) | Oracle 价格         |
| `supply_raw`                            | NUMERIC(40,0) | 链上原始供给整数    |
| `supply_usd`                            | NUMERIC(30,8) | 供给 USD 估值       |
| `stable_debt_raw` / `variable_debt_raw` | NUMERIC(40,0) | 链上原始借贷整数    |
| `total_debt_usd`                        | NUMERIC(30,8) | 借贷 USD 估值       |
| `use_as_collateral`                     | BOOLEAN       | 是否用作抵押品      |

写入策略：**全量 UPSERT**，每次爬取覆盖最新快照。

### 来源表（`loan.aave_{v2|v3}_eth_weth_{collateral|borrow}`）

由 `sync-addresses` 命令写入，也可由 subgraph 外部维护（两者均支持）。

| 列                                     | 类型          | 说明                                             |
| -------------------------------------- | ------------- | ------------------------------------------------ |
| `walletAddress`                        | TEXT PK       | 用户地址                                         |
| `wethAmount_ETH` 或 `borrowedWeth_ETH` | NUMERIC(30,8) | 历史累计 ETH 量（供 `> 0` 过滤用）               |
| `synced_at`                            | TIMESTAMPTZ   | 最近同步时间（仅 `sync-addresses` 写入时有此列） |

### `aave.aave_history`（链上历史事件，由 chain-data-collector 维护）

用于历史仓位重建与用户地址派生。关键字段：

| 字段               | 说明                                  |
| ------------------ | ------------------------------------- |
| `user_address`     | bytea（存 ASCII `0x...` 字符串）      |
| `token_symbol`     | TEXT，如 `WETH`、`wstETH`             |
| `operation_type`   | TEXT，如 `deposit`、`borrow`、`repay` |
| `protocol_version` | TEXT，`2` 或 `3`                      |
| `amount`           | NUMERIC，原始整数                     |
| `decimals`         | INTEGER                               |
| `created_at`       | TIMESTAMPTZ                           |

---

## 项目结构

```text
backend/
├── pyproject.toml
├── config.yaml.example
├── config.yaml              # 本地配置（gitignored）
├── scripts/                 # 研究/一次性脚本
│   ├── derive_users_from_events.py   # 从链上事件派生用户地址（对比分析）
│   ├── check_data_range.py           # ULID 时间戳范围检查
│   └── recalc_liq_price*.py          # 重新计算大批量清算价
├── derived_users/           # derive 脚本的 CSV 输出（gitignored）
├── tests/
│   ├── conftest.py          # pytest fixtures & mock 数据
│   └── test_routes.py       # 路由单元测试（全 mock，无需真实 DB/RPC）
└── aave_crawler/
    ├── cli.py               # Click CLI 入口（aave-crawler 命令）
    ├── server.py            # FastAPI app 工厂 + uvicorn 入口（aave-api 命令）
    ├── config.py            # 配置加载
    ├── models.py            # 数据模型（dataclass）
    ├── rpc.py               # 合约调用（web3.py AsyncWeb3）
    ├── db.py                # asyncpg：DDL、UPSERT、sync_addresses_from_history
    ├── crawler.py           # 并发批量爬取主流程
    ├── watcher.py           # 增量监听主流程
    └── api/
        ├── constants.py     # ETH 系资产符号、过滤阈值常量
        ├── schemas.py       # Pydantic 响应模型
        ├── service.py       # 业务逻辑（仓位查询、清算价计算、模拟清算、价格序列）
        └── routes.py        # FastAPI 路由
```

---

## 开发

### 运行测试

```bash
uv run pytest tests/ -q
```

### 常用 uv 命令

```bash
uv add some-package           # 添加运行时依赖
uv add --dev some-package     # 添加开发依赖
uv run python your_script.py  # 在项目虚拟环境中运行脚本
```

### 合约地址（以太主网）

| 合约                | 地址                                         |
| ------------------- | -------------------------------------------- |
| Aave V3 Pool        | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` |
| V3 PoolDataProvider | `0x7B4EB56E7CD4b454BA8ff71E4518426369a138a3` |
| V3 Aave Oracle      | `0x54586bE62E3c3580375aE3723C145253060Ca0C2` |
| Aave V2 Pool        | `0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9` |
| V2 PoolDataProvider | `0x057835Ad21a177dbdd3090bB1CAE03EaCF78Fc6d` |
| V2 Aave Oracle      | `0xA50ba011c48153De246E5192C8f9258A2ba79Ca9` |
