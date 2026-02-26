# aave-crawler（后端）

批量查询 Aave V3 Base Mainnet 上所有用户的仓位，并持久化到 PostgreSQL。

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
    ├── cli.py               # Click CLI 入口
    ├── config.py            # 配置加载
    ├── models.py            # 数据模型（dataclass）
    ├── rpc.py               # 合约调用（web3.py AsyncWeb3）
    ├── db.py                # asyncpg，DDL + UPSERT
    └── crawler.py           # 并发批量爬取主流程
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
