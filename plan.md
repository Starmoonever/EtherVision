# JustLend 市场数据建设分阶段执行计划

本文档用于规划 JustLend 市场数据能力的落地路径，覆盖表设计、数据获取、接口设计、测试与文档同步。

适用范围：

- `backend/justlend_crawler/`
- `backend/scripts/justlend/`
- `backend/alembic/`
- `backend/tests/`
- `backend/README.md`

约束前提：

- 以当前仓库真实实现为准，不假设外部 schema 可被本仓库修改
- 新增 TRON 地址相关字段时，目标标准为 Base58 文本地址，且以 `T...` 形式存储
- 批量写入与回填脚本优先使用 `asyncpg`
- API 设计尽量贴近现有 Compound market state 风格，降低前端接入成本

---

## 总体目标

为 JustLend 增加可持续维护的市场数据能力，形成以下闭环：

1. 能稳定拉取市场基础元数据与状态数据
2. 能将最新状态和历史快照持久化到 PostgreSQL
3. 能通过统一 API 提供最新市场列表、单市场状态、区间状态查询
4. 能通过测试和文档保证后续维护成本可控

---

## 阶段 0：现状确认与设计冻结

### 目标

在开始编码前冻结最小可行方案，避免后续在地址格式、表命名、字段口径上反复返工。

### 执行计划

- 盘点现有 JustLend 相关能力：
  - 已有用户仓位表与回放表
  - 已有 `/lend/jtoken` 市场 API 使用逻辑
  - 已有 TRON RPC 调用工具与 `fetch_market_exchange_rates`
  - 已有 `tx_position_replay.py` 可作为脚本结构参考
- 明确本次范围只做“市场数据”，不改动现有用户仓位回放主流程
- 明确新表地址字段采用 Base58 文本存储，不延续旧 `BYTEA` 方案到新表
- 明确市场数据来源分层：
  - OpenAPI：市场列表、symbol、underlying、`underlyingPriceInTrx`、`collateralFactor`
  - TRON RPC：exchange rate、cash、borrows、reserves、利率、控制器与预言机等链上状态
- 明确第一版 API 范围：
  - `GET /api/justlend/markets`
  - `GET /api/justlend/market/state`
  - `GET /api/justlend/market/state/period`

### 交付物

- 本 `plan.md`
- 字段草案和范围定义达成一致

### 验收标准

- 已明确哪些字段来自 OpenAPI，哪些字段来自 RPC
- 已明确新表采用 Base58 文本地址
- 已明确最新态和历史快照分表，而不是混入现有 position 表
- 已明确第一版不包含 watcher 自动增量逻辑

### Checklist

- [x] 确认新增能力不依赖修改外部 schema
- [x] 确认市场数据与用户仓位数据的边界
- [x] 确认地址存储标准与兼容策略
- [x] 确认第一版 API 范围
- [x] 确认脚本入口命名与职责

---

## 阶段 1：数据库模型与迁移落地

### 目标

建立 JustLend 市场数据的可落库结构，支持“最新状态查询”和“历史时间序列查询”。

### 执行计划

- 新增 Alembic migration
- 新增两张核心表：
  - `loan.justlend_markets_current`
  - `loan.justlend_market_snapshots`
- 根据查询需求设计索引
- 对 TRON 地址字段统一使用文本列，并显式设置 `STORAGE PLAIN`

### 推荐表结构

#### 1. `loan.justlend_markets_current`

用于保存每个市场的最新状态，每个市场一行。

建议字段：

- `market_address TEXT PRIMARY KEY`
- `chain TEXT NOT NULL DEFAULT 'tron'`
- `protocol TEXT NOT NULL DEFAULT 'justlend'`
- `market_type TEXT NOT NULL DEFAULT 'jtoken'`
- `underlying_address TEXT`
- `comptroller_address TEXT`
- `oracle_address TEXT`
- `symbol TEXT`
- `underlying_symbol TEXT`
- `underlying_decimals INTEGER`
- `jtoken_decimals INTEGER`
- `is_listed BOOLEAN`
- `is_entered_supported BOOLEAN`
- `collateral_factor NUMERIC(20, 18)`
- `reserve_factor NUMERIC(20, 18)`
- `borrow_cap NUMERIC(40, 18)`
- `supply_cap NUMERIC(40, 18)`
- `exchange_rate NUMERIC(40, 18)`
- `cash NUMERIC(40, 18)`
- `total_borrows NUMERIC(40, 18)`
- `total_reserves NUMERIC(40, 18)`
- `utilization NUMERIC(20, 18)`
- `borrow_rate NUMERIC(38, 18)`
- `supply_rate NUMERIC(38, 18)`
- `underlying_price_in_trx NUMERIC(30, 12)`
- `price_usd NUMERIC(30, 8)`
- `snapshot_at TIMESTAMPTZ NOT NULL`
- `block_timestamp TIMESTAMPTZ`
- `block_number BIGINT`
- `extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

#### 2. `loan.justlend_market_snapshots`

用于保存按时间采集的历史状态。

建议字段：

- `snapshot_at TIMESTAMPTZ NOT NULL`
- `market_address TEXT NOT NULL`
- 其余业务字段与 `justlend_markets_current` 基本一致
- `PRIMARY KEY (snapshot_at, market_address)`

### 索引建议

- `justlend_markets_current(updated_at DESC)`
- `justlend_markets_current(underlying_address)`
- `justlend_markets_current(symbol)`
- `justlend_market_snapshots(market_address, snapshot_at DESC)`
- `justlend_market_snapshots(snapshot_at DESC)`
- `justlend_market_snapshots(underlying_address, snapshot_at DESC)`

### 设计说明

- `current` 表负责最新态查询，避免每次都扫历史表
- `snapshots` 表负责趋势图和历史回溯
- 将复杂或暂不稳定的原始字段放入 `extra_jsonb`，避免过早固化所有字段
- 如链上方法短期无法稳定返回 `borrow_cap` / `supply_cap`，允许先写 `NULL`，但需在文档说明

### 交付物

- Alembic migration 文件
- `justlend_crawler/db.py` 中对应建表/写入/查询辅助函数

### 验收标准

- 本地 `alembic upgrade head` 可创建新表
- 新表字段可覆盖第一版 API 返回所需数据
- 新表中 TRON 地址字段为 Base58 文本而非 `BYTEA`
- 索引可支撑 `latest` 与 `period` 两类查询

### Checklist

- [x] 确认表名与仓库命名风格一致
- [x] 确认地址字段全部为 Base58 文本
- [x] 确认主键与唯一键满足 upsert 需求
- [x] 确认索引覆盖核心查询路径
- [x] 确认 `extra_jsonb` 已预留
- [x] 确认 migration 可重复执行或具备存在性保护

---

## 阶段 2：市场数据采集能力实现

### 目标

实现单次全量市场抓取，得到可直接落库的标准化市场数据对象。

### 执行计划

- 在 `backend/justlend_crawler/rpc.py` 中补齐市场级 RPC 调用封装
- 在 `backend/justlend_crawler/api/service.py` 或独立 service 层中实现市场数据标准化逻辑
- 复用现有 `_fetch_justlend_market_catalog()`，避免重复解析 `/lend/jtoken`
- 将 OpenAPI 与 RPC 结果合并为统一的 market state 数据结构

### 推荐实现拆分

#### OpenAPI 层

负责拉取：

- 市场地址
- underlying 地址
- underlying symbol
- underlying decimals
- `underlyingPriceInTrx`
- `collateralFactor`

推荐复用或扩展：

- `_fetch_justlend_market_catalog()`

#### RPC 层

负责补充：

- `exchangeRateStored()` 或对应方法
- `getCash()`
- `totalBorrows()`
- `totalReserves()`
- `reserveFactorMantissa()`
- `borrowRatePerBlock()` / `supplyRatePerBlock()` 或协议对应方法
- `comptroller()`
- `oracle()`
- `underlying()`
- `symbol()`
- `decimals()`
- `markets(address)`

#### 标准化层

将不同来源统一成单个结构，例如：

- `market_address`
- `underlying_address`
- `symbol`
- `underlying_symbol`
- `price_usd`
- `exchange_rate`
- `cash`
- `total_borrows`
- `total_reserves`
- `utilization`
- `borrow_rate`
- `supply_rate`
- `block_number`
- `snapshot_at`
- `extra_jsonb`

### 风险点

- JustLend 不同 jToken 可能存在 ABI 差异
- 某些 RPC 字段可能偶发返回空值或 revert
- `borrow_cap` / `supply_cap` 不一定所有市场都能统一获取
- 年化口径可能与 UI 预期不一致，需要明确返回原始 rate 还是 APR

### 应对策略

- 单市场抓取失败不阻塞全量任务，记录 warning 并继续
- 原始 RPC 返回可落入 `extra_jsonb.raw_rpc`
- 对无法获取的字段允许 `NULL`
- 年化计算逻辑固定在 service 层，避免 API 和脚本重复实现

### 交付物

- 市场级 RPC 函数
- 标准化 market state 构造函数
- 单次全量抓取的 service 函数

### 验收标准

- 给定一组 market 地址，能返回结构完整的市场数据列表
- 单个市场失败不会导致全量流程整体崩溃
- 返回结构可直接供 DB upsert 和 API 返回复用
- 采集过程能区分 OpenAPI 字段和 RPC 字段来源

### Checklist

- [x] 复用现有 `/lend/jtoken` 抓取逻辑
- [x] 补齐市场级 RPC 调用
- [x] 统一数值精度与字符串/Decimal 处理
- [ ] 明确 rate/APR 口径
- [x] 处理部分字段缺失或 RPC revert
- [x] 为日志记录保留足够上下文

当前补充说明：

- 官方 `GET https://openapi.just.network/lend/jtoken` 已确认提供 `cash`、`totalBorrows`、`totalSupply`、`reserves`、`exchangeRate`、`reserveFactor`、`supplyRate`、`borrowRate`
- 当前实现已支持从 OpenAPI 解析 `borrowCap` / `supplyCap` 及其常见变体字段
- 但截至当前核对结果，官方 OpenAPI 实际响应中未观测到 cap 字段；公开 `justlend-protocol` `Comptroller.sol` 也未发现 `borrowCaps` / `supplyCaps` 方法
- 因此 `borrow_cap` / `supply_cap` 的剩余问题已从“代码未解析”收敛为“当前官方数据源未提供”

---

## 阶段 3：回填脚本与落库流程

### 目标

提供一个可直接执行的脚本，将 JustLend 市场数据抓取并写入数据库。

### 执行计划

- 新建脚本：
  - `backend/scripts/justlend/market_state_backfill.py`
- 参考 `tx_position_replay.py` 的结构复用以下能力：
  - 配置加载
  - `asyncpg` pool 生命周期
  - CLI 参数解析
  - dry-run 模式
- 第一版脚本优先支持“抓当前最新状态并落两张表”
- 第二版再考虑按时间点循环抓取历史数据

### 建议 CLI 参数

- `--config`
- `--market`，可重复传入
- `--limit`
- `--dry-run`
- `--snapshot-at`
- `--write-snapshots`
- `--skip-current`
- `--verbose`

### 运行模式建议

#### 模式 A：latest 刷新

- 全量抓取所有可用市场
- upsert 到 `justlend_markets_current`
- 同时插入一份 `justlend_market_snapshots`

#### 模式 B：历史点回填

- 传入一个或多个时间点
- 按时间点循环写入 `justlend_market_snapshots`
- 如缺少历史区块能力，第一版可暂不支持精确历史块高回放

### 关键实现点

- upsert current 表
- append snapshot 表
- 脚本输出成功数、失败数、跳过数
- dry-run 时打印摘要但不写库

### 交付物

- `backend/scripts/justlend/market_state_backfill.py`
- `db.py` 中配套 upsert/query 函数

### 验收标准

- 脚本可在本地执行并输出统计信息
- `--dry-run` 不写库但能完成抓取
- 默认执行可更新 current 表并插入 snapshot 表
- 单个市场失败时脚本最终退出行为可预测，并能看到失败摘要

### Checklist

- [x] 新脚本命名和职责明确
- [x] CLI 参数与现有脚本风格一致
- [x] 支持 dry-run
- [x] 支持按 market 过滤
- [x] 支持 current/snapshot 分别控制写入
- [x] 输出成功/失败统计

---

## 阶段 4：API 设计与只读查询实现

### 目标

向前端和调试调用方暴露 JustLend 市场数据查询接口。

### 执行计划

- 扩展 `backend/justlend_crawler/api/schemas.py`
- 扩展 `backend/justlend_crawler/api/service.py`
- 扩展 `backend/justlend_crawler/api/routes.py`
- 将现有空实现的 `/api/justlend/markets` 改为真实市场列表查询

### 推荐接口

#### 1. `GET /api/justlend/markets`

用途：

- 返回当前数据库中最新市场列表

建议字段：

- `chain`
- `protocol`
- `markets`
  - `market`
  - `symbol`
  - `underlying_address`
  - `underlying_symbol`
  - `updated_at`

#### 2. `GET /api/justlend/market/state`

用途：

- 查询单个市场最新状态
- 可选支持 `date` 参数查询某个时间点前最近一条

建议参数：

- `market`
- `date` 可选
- `detail` 可选

建议返回：

- `market`
- `symbol`
- `timestamp`
- `underlying`
- `underlying_symbol`
- `total_supply`
- `total_borrow`
- `total_reserves`
- `utilization`
- `borrow_apr`
- `supply_apr`
- `price_usd`
- `exchange_rate`
- `collateral_factor`
- `reserve_factor`
- `extra`

#### 3. `GET /api/justlend/market/state/period`

用途：

- 查询一个市场在时间区间内的状态变化

建议参数：

- `market`
- `start`
- `end`
- `interval` 可选
- `latest_only_per_day` 可选

建议返回：

- `points: list[JustLendMarketStateResponse]`

### 设计原则

- 尽量贴近 Compound 的 `market_state` 响应结构
- API 返回地址统一为 Base58 文本
- 时间字段统一 UTC ISO8601
- 详情字段可通过 `detail=false` 做裁剪，避免响应膨胀

### 交付物

- 新增 schemas
- 新增 service 查询函数
- 新增 routes

### 验收标准

- `/api/justlend/markets` 不再返回空列表占位
- 能查询单市场 latest 状态
- 能查询单市场 period 状态
- 响应字段命名和精度稳定，可供前端直接消费

### Checklist

- [x] `markets` 接口改为真实查询
- [x] 增加 single market state 接口
- [x] 增加 market state period 接口
- [x] 响应地址统一为 Base58
- [x] 时间格式统一为 UTC ISO8601
- [x] 与现有 Compound 风格尽量对齐

---

## 阶段 5：测试与质量保障

### 目标

保证新增市场数据链路在重构和后续扩展中可验证、可回归。

### 执行计划

- 新增单元测试，覆盖：
  - OpenAPI payload 解析
  - RPC payload 解析
  - 市场状态标准化
  - DB upsert/query
  - API route 返回
- 对脚本至少补核心逻辑测试或 service 层测试
- 保证失败路径可测

### 建议测试文件

- `backend/tests/test_justlend_market_service.py`
- `backend/tests/test_justlend_market_routes.py`
- 如有需要：
  - `backend/tests/test_justlend_market_db.py`

### 必测场景

- OpenAPI 返回正常市场列表
- 部分市场 RPC 返回空或失败
- 单市场 latest 查询命中
- 单市场 period 查询命中
- 地址格式统一输出为 Base58
- dry-run 模式不写库
- 数值字段精度不丢失

### 交付物

- 测试文件
- 必要的 mock 数据

### 验收标准

- 新增测试可运行
- 关键成功路径和失败路径均被覆盖
- 至少覆盖一个“部分失败但整体成功”的场景
- API 与 service 的核心行为有自动化验证

### Checklist

- [x] 补 service 测试
- [x] 补 route 测试
- [ ] 补数据库读写测试或等效覆盖
- [x] 覆盖部分失败场景
- [x] 覆盖地址标准化场景
- [ ] 覆盖 dry-run 场景

---

## 阶段 6：文档同步与上线前检查

### 目标

确保新增能力在仓库文档中可被发现、可被运行、可被维护。

### 执行计划

- 更新 `backend/README.md`
- 如根 README 需要增加 JustLend 市场数据导航，则同步更新根 `README.md`
- 明确以下内容：
  - 新增数据库表
  - 回填脚本命令
  - 新增 API 路由
  - 地址格式标准说明
  - 当前限制与已知缺口

### 文档应明确说明的限制

- 某些市场字段可能来自 OpenAPI，某些来自 RPC
- 历史精确回放能力如果尚未实现，应明确写明“当前仅支持采集时点快照”
- `borrow_cap`、`supply_cap` 等字段若暂不可得，需要注明为空的原因

### 上线前检查

- migration 可升级
- 脚本可 dry-run
- 脚本可真实写库
- API 可读取真实数据
- 测试通过
- 文档已更新

### 交付物

- 更新后的 README 文档
- 上线前检查记录

### 验收标准

- 新成员只看文档即可完成：
  - 建表
  - 跑脚本
  - 调接口
- 文档没有把“目标标准”误写成“当前事实”
- 文档明确区分内部表与外部依赖

### Checklist

- [x] 更新 `backend/README.md`
- [ ] 如有必要更新根 `README.md`
- [x] 说明新表与脚本入口
- [x] 说明 API 路由
- [x] 说明当前限制与后续方向
- [ ] 完成上线前检查

---

## 推荐实施顺序

1. 阶段 0：冻结范围与口径
2. 阶段 1：先落 migration 和 DB helper
3. 阶段 2：完成市场采集与标准化
4. 阶段 3：补回填脚本
5. 阶段 4：开放 API 查询
6. 阶段 5：补测试
7. 阶段 6：补 README 与上线检查

---

## 第一版范围边界

为控制复杂度，第一版建议明确不做以下事项：

- 不改造现有 JustLend 用户仓位与回放表结构
- 不引入 watcher 常驻增量同步
- 不承诺所有市场都能拿到完整链上治理参数
- 不承诺立即支持任意历史块高下的精确市场状态回放
- 不把外部 schema 当作本仓库迁移管理对象

---

## 完成定义

当满足以下条件时，可认为 JustLend 市场数据第一版完成：

- 数据库中存在 JustLend 市场 current 与 snapshot 表
- 存在可执行的市场回填脚本
- API 可查询市场列表、单市场最新状态、单市场时间区间状态
- 测试覆盖核心成功路径与失败路径
- README 已同步说明运行方式和限制
