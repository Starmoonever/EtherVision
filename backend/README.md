# 后端说明

`backend/` 是本仓库的统一后端服务目录，负责多协议数据采集、数据库持久化、历史回放与 API 暴露。

当前主要覆盖：

- Aave
- Compound
- Morpho
- JustLend

如果你是第一次接手本仓库，建议先看根 [README.md](../README.md)，再回到本文件看后端细节。

## 技术栈

- Python 3.12+
- `uv`
- FastAPI
- asyncpg
- SQLAlchemy AsyncSession
- Alembic
- web3.py
- 可选：ClickHouse

## 目录结构

```text
backend/
├── README.md
├── pyproject.toml
├── alembic/
├── aave_crawler/
├── compound_crawler/
├── morpho_crawler/
├── justlend_crawler/
├── crawler_shared/
├── scripts/
└── tests/
```

### 协议模块

- `aave_crawler/`
  - Aave 地址同步、仓位快照、历史回放、价格与清算分析
- `compound_crawler/`
  - Compound V2/V3 市场、治理、用户仓位与回放
- `morpho_crawler/`
  - Morpho Blue 市场、当前用户仓位与按请求懒加载的历史 replay
- `justlend_crawler/`
  - JustLend 当前仓位、趋势回放、事件说明
- `crawler_shared/`
  - 共享配置、数据库、统一 API 入口与公共组件

### 其他目录

- `alembic/`
  - 数据库迁移脚本
- `scripts/`
  - 回填、校验、探索、诊断脚本
- `tests/`
  - pytest 测试

## 安装依赖

```bash
cd backend
uv sync
```

## 配置

### 必要文件

- `backend/config.yaml`

该文件已被 `.gitignore` 忽略，通常从 `config.yaml.example` 复制后修改。

### 常见配置内容

- RPC 节点地址
- PostgreSQL 连接信息
- 可选的 ClickHouse 连接信息
- crawler 并发、批大小、超时、重试
- watcher 轮询间隔与回看窗口

### 配置查找顺序

后端配置通常按以下顺序查找：

1. 显式传入的配置路径
2. 当前工作目录下的 `config.yaml`
3. `backend/config.yaml`

## 价格查询约定

统一价格接口 `GET /api/price` 与 `GET /api/price/period` 当前对 Ethereum 资产采用 15 分钟时间桶语义：

- 历史价格请求会先将请求时间对齐到 15 分钟桶，再查缓存或外部价格源
- `loan.eth_price_timestamp` 虽然沿用历史表名，但实际存储的是 Ethereum 链上多资产的历史 USD 价格缓存，不是仅限 ETH 代币
- 代码层已优先使用 `ensure_ethereum_price_cache_table`、`get_cached_ethereum_price_usd`、`upsert_ethereum_price_cache` 这组 helper；旧的 `eth_*` helper 名称仅保留兼容
- `GET /api/price/period` 返回的时间点同样是桶时间，不再表示秒级精确成交时间
- 当前该套历史价格桶缓存只覆盖 Ethereum 资产，暂不包含 TRON

TRON 价格查询的现状与约定：

- `/api/price` 与 `/api/price/period` 已支持通过 `chain=tron` 或 TRON Base58 地址查询波场资产
- TRON 小粒度价格缓存表为 `loan.tron_price_timestamp`，地址统一存储为规范化 Base58 `T...` 文本，并使用列级 `STORAGE PLAIN`
- `loan.tron_price_timestamp` 采用“懒更新”模式：查询命中缓存则直接返回；查询未命中时，仅在当前 15 分钟桶触发一次 JustLend 市场接口抓取并回填该桶
- 对于未命中的历史 TRON bucket，当前仍回退到 `loan.justlend_market_snapshots` 中最近的市场快照；如果该表只有日级快照，则返回结果粒度也会受限于现有快照密度

## 常用命令

### 启动 API

```bash
cd backend
uv run api
```

常见变体：

```bash
uv run api --reload
uv run api --port 8080 --workers 4
```

### Aave CLI

```bash
uv run aave-crawler sync-addresses
uv run aave-crawler crawl -p v3
uv run aave-crawler crawl -p v3_borrow
uv run aave-crawler watch -p v3
uv run aave-crawler check 0xAddress
```

协议参数常见取值：

- `v2`
- `v3`
- `v2_borrow`
- `v3_borrow`

### 其他协议 CLI

项目脚本入口定义在 `pyproject.toml`：

- `uv run compound-crawler`
- `uv run morpho-crawler`
- `uv run justlend-crawler`

如果需要新增协议级命令，优先检查各自 `cli.py` 与 `crawler_shared.server` 的集成方式。

## 数据库访问模式

本项目采用双数据库访问模式。

### SQLAlchemy AsyncSession

适合：

- API 读操作
- ORM 模型管理
- Alembic 迁移源

优势：

- 类型更清晰
- 模型边界更明确
- 对维护者更友好

### asyncpg Pool

适合：

- 批量写入
- `COPY` 协议
- 显式事务
- 性能关键路径
- 批处理脚本与缓存写入

经验规则：

- API 查询默认优先 SQLAlchemy
- 批量落库、批处理、回放缓存优先 asyncpg

## 各协议后端职责

### Aave

Aave 目前仍是后端中历史最重的模块，包含：

- 用户地址同步
- 当前仓位快照
- 日级仓位与资产明细
- 历史交易回放
- ETH 价格相关清算分析

关键约定：

- `liq_price` 表示 ETH 下跌触发的清算价格
- `liq_price_rise` 表示 ETH 上涨触发的 WETH 借款清算价格
- Aave V2 与 V3 的 oracle 单位处理不同，改动相关逻辑时必须重新核对

### Compound

Compound 模块负责：

- 市场状态
- 治理参数与配置版本
- 用户仓位快照
- 当前仓位缓存与历史回放

该模块大量使用 `BYTEA` 存储地址类字段，维护时要注意 API 层与数据库层之间的编码转换。

### Morpho

Morpho 模块当前聚焦 Morpho Blue：

- 当前用户仓位查询
- 市场信息缓存
- 单市场个人仓位 replay
- 资产与额外信息的 JSONB 存储

Morpho 写路径里已经有较明确的“API 文本地址 -> DB bytes”的转换逻辑，改动时要连同读路径一起核对。

当前 Morpho replay 的实现约定：

- 接口为 `GET /api/morpho/position/replay`
- 目前只支持单市场 replay，调用时必须传 `market_id`
- replay 走“先查表，未命中再实时构建并写回缓存”的模式，不做批量回填
- replay 快照表为 `loan.morpho_blue_position_snapshots`
- replay 依赖历史区块 `eth_call` 与事件日志查询，生产环境应提供 archive 能力较完整的 EVM RPC

`brief` 生成规则当前按 Morpho 事件聚合：

- `supply` / `withdraw` / `borrow` / `repay` 使用 loan token 金额
- `supplyCollateral` / `withdrawCollateral` 使用 collateral token 金额
- 同一笔交易内若有多条相关事件，会按日志顺序合并成一个 `brief`
- `liquidate` 当前面向 borrower 生成“被清算”说明

### JustLend

JustLend 模块负责：

- 当前仓位查询
- 市场列表与市场状态查询
- 市场最新态缓存与历史快照
- 用户趋势回放
- 交易 effect 解释
- TRON 地址与说明文案处理

这里的重点不是 EVM `0x...` 地址，而是 TRON Base58 地址与内部兼容表示之间的转换。

当前已新增的 JustLend 市场数据表包括：

- `loan.justlend_markets_current`
- `loan.justlend_market_snapshots`

设计约束：

- 新增 JustLend 市场地址类字段按 Base58 文本存储
- `current` 表用于最新状态查询
- `snapshots` 表用于时间序列与区间查询

当前新增的 JustLend 市场接口包括：

- `GET /api/justlend/markets`
- `GET /api/justlend/market/state`
- `GET /api/justlend/market/state/period`

当前可用的 JustLend 市场回填脚本：

```bash
cd backend
uv run python scripts/justlend/market_state_backfill.py --dry-run
uv run python scripts/justlend/market_state_backfill.py --market <MARKET_ADDRESS>
```

说明：

- 第一版先打通数据库与只读查询链路
- 当前脚本默认抓取最新市场状态，不提供任意历史块高回放
- `borrow_cap`、`supply_cap` 等字段在第一版中仍可能为空，后续按可用链上方法补齐

## 数据库与迁移

### Alembic

常用命令：

```bash
cd backend
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
uv run alembic downgrade -1
```

注意：

- Alembic 不覆盖所有外部 schema
- 自动生成迁移后必须人工复核
- 提交前至少跑一次升级验证

### 外部依赖表

仓库中的部分逻辑依赖外部维护表，例如历史事件表。这些表不一定由本仓库拥有，也不一定能通过 Alembic 统一管理。

因此：

- 不要默认外部 schema 可以随意改
- 不要把外部表的当前形态误写成仓库内部标准
- 如依赖其字段语义，应在代码或文档中明确标注

## 地址与存储约定

当前仓库存在历史遗留的多种地址存储格式。后续统一标准见根目录 [AGENTS.md](../AGENTS.md)。

维护时请区分两件事：

- 当前某张表实际上怎么存
- 后续新增或重构时应该朝什么标准迁移

尤其要避免：

- 把“后续标准”写成“现状”
- 在未核对上下游前，直接统一旧表地址编码
- 在 TRON 场景把 `T...` 地址与 hex/raw bytes 混用

## 测试

常用命令：

```bash
cd backend
uv run pytest tests/ -q
uv run pytest tests/test_routes.py -v
```

仓库中已经包含：

- Aave 路由与服务测试
- Compound 数据库与服务测试
- Morpho 服务测试
- JustLend 路由与服务测试
- 价格服务测试

## 常见坑

### 1. 不要把 backend 当成只有 Aave

虽然历史文档和很多脚本偏向 Aave，但当前后端已经是多协议统一服务。改文档或 API 时，要确认是否影响 Compound、Morpho、JustLend。

### 2. 地址字段不是全库统一现状

仓库内不同模块、不同历史阶段的地址存储格式并不一致。任何“统一化”动作都需要先做现状核对。

### 3. 外部 schema 不是 Alembic 的默认管理对象

如果你看到查询里用到了外部 schema，不要直接把它当成可以通过本仓库迁移控制的对象。

### 4. Aave oracle 逻辑不能凭记忆改

V2 和 V3 的价格单位差异是真实存在的，修改仓位计算时必须重新核对。

### 5. 文档要分层维护

- 仓库入口变更：更新根 `README.md`
- 后端行为变更：更新本文件
- 前端运行方式变更：更新 `frontend/README.md`
