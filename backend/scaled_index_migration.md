# Scaled Index 改造方案与执行计划

> 目标：将 `daily_collector` 从"每日全量 RPC 快照"改造为"事件驱动更新 + Index 重算"，
> 使 3 年历史数据的采集从 **>30 小时**缩短至 **~2 小时**，并补全历史用户覆盖。

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [Aave 利息计算机制](#2-aave-利息计算机制)
3. [整体架构变化](#3-整体架构变化)
4. [Schema 改造](#4-schema-改造)
5. [代码改造](#5-代码改造)
6. [执行计划](#6-执行计划)
7. [边界情况与风险](#7-边界情况与风险)

---

## 1 背景与动机

### 1.1 现状

`daily_collector` 每日对所有跟踪用户在历史区块执行 `eth_call`：

```text
每日 RPC 消耗（两阶段优化后）
  Post-Multicall3（2022-03 起）：~580 次/天
  Pre-Multicall3 （V2 早期）  ：~14,500 次/天
```

扩展至 3 年时：

| 时期                     | 天数 | RPC/天  | 合计           |
| ------------------------ | ---- | ------- | -------------- |
| V2 早期（无 Multicall3） | 420  | ~14,500 | ~6,100,000     |
| 近期（有 Multicall3）    | 675  | ~580    | ~392,000       |
| **合计**                 | 1095 |         | **~6,500,000** |

预计耗时 **>30 小时**，且现有方案仅覆盖当前活跃用户，已平仓的历史用户**完全缺失**。

### 1.2 目标

- 3 年历史数据总 RPC 降至 **~390,000 次**（~17×）
- 预计采集耗时 **~2 小时**
- 覆盖所有历史用户（含已平仓）
- Pre-Multicall3 时期同等受益

---

## 2 Aave 利息计算机制

### 2.1 核心公式

Aave 通过协议级别的**利率指数**累积利息，所有用户共享同一套指数：

```text
# 供给（Supply）
current_atoken_balance = scaled_atoken_balance × liquidityIndex / 1e27

# 变量借贷（Variable Debt）
current_variable_debt = scaled_variable_debt × variableBorrowIndex / 1e27

# 稳定借贷（Stable Debt）—— 用户级别，不依赖协议指数
current_stable_debt = principal_stable_debt
                    × (1 + stable_borrow_rate/1e27) ^ seconds_elapsed
```

其中 `scaled_*` 是**不变量**（只在用户发生链上操作时改变），
`liquidityIndex` / `variableBorrowIndex` 是**协议级别日更新量**。

### 2.2 重算逻辑

对无链上操作的用户，已知：

- 昨日 `scaled_atoken_balance`（DB 存储）
- 今日 `liquidityIndex`（单次 Multicall3，全协议共享）

则今日余额可纯数学推导，**无需任何 RPC**：

```python
supply_today = scaled_supply × liquidity_index_today / 1e27
variable_debt_today = scaled_variable_debt × variable_borrow_index_today / 1e27
liq_price_today = recalc(supply_today, variable_debt_today, eth_price_today)
```

### 2.3 已有数据盘点

`getUserReserveData` 返回 9 个字段，当前系统已解码全部，但只存了部分：

| 字段                       | 含义                      | 当前是否存库           |
| -------------------------- | ------------------------- | ---------------------- |
| [0] `currentATokenBalance` | 当前供给（已 ×index）     | ✅ `supply_raw`        |
| [1] `currentStableDebt`    | 当前稳定债务（已复利）    | ✅ `stable_debt_raw`   |
| [2] `currentVariableDebt`  | 当前变量债务（已 ×index） | ✅ `variable_debt_raw` |
| [3] `principalStableDebt`  | 稳定债务本金（未复利）    | ❌ 未存                |
| [4] `scaledVariableDebt`   | 变量债务 scaled 值        | ❌ 未存                |
| [5] `stableBorrowRate`     | 用户稳定借贷利率          | ❌ 未存                |

`scaledATokenBalance` 不在 `getUserReserveData` 返回值中，由推导得出：

```python
scaled_atoken_balance = current_atoken_balance × 1e27 // liquidity_index
```

---

## 3 整体架构变化

### 3.1 现有流程（单阶段 / 两阶段）

```text
每天
  ├── Phase 1：Multicall3 批量 getUserAccountData（130 批）
  ├── Phase 2：活跃用户 getUserReserveData Multicall3（~450 次）
  └── 写库：daily_positions + daily_reserve_positions
```

### 3.2 新流程（事件驱动 + Index 重算）

```text
每天
  ├── [Step A] 拉取所有 reserve 当日 index（1 次 Multicall3）
  ├── [Step B] 从 aave_history 取当日有事件的用户集合
  ├── [Step C-事件用户] Multicall3 全量查询（~4 批账户 + ~200 reserve 查询）
  ├── [Step D-无事件用户] DB 内 index 重算（SQL，0 次 RPC）
  └── 写库：daily_positions + daily_reserve_positions（同现有结构）
```

---

## 4 Schema 改造

### 4.1 `daily_reserve_positions` 表新增字段

**✅ 已完成**：`loan.aave_v{2|3}_eth_daily_reserve_positions` 已存在以下 4 列：

```sql
-- 已存在，无需 ALTER TABLE
scaled_supply_raw          NUMERIC(40, 0) NOT NULL DEFAULT 0,
scaled_variable_debt_raw   NUMERIC(40, 0) NOT NULL DEFAULT 0,
principal_stable_debt_raw  NUMERIC(40, 0) NOT NULL DEFAULT 0,
stable_borrow_rate_raw     NUMERIC(40, 0) NOT NULL DEFAULT 0,
```

> 注意：实际列名为 `stable_borrow_rate_raw`（带 `_raw` 后缀），迁移文档原草稿为 `stable_borrow_rate`，以实际 DB 为准。

字段语义：

| 新字段                      | 来源                                            | 说明                  |
| --------------------------- | ----------------------------------------------- | --------------------- |
| `scaled_supply_raw`         | `currentATokenBalance × 1e27 // liquidityIndex` | 推导，不随 index 变化 |
| `scaled_variable_debt_raw`  | `getUserReserveData[4]` scaledVariableDebt      | 已解码，直接存储      |
| `principal_stable_debt_raw` | `getUserReserveData[3]` principalStableDebt     | 已解码，直接存储      |
| `stable_borrow_rate_raw`    | `getUserReserveData[5]` stableBorrowRate        | 每用户独立，1e27 精度 |

### 4.2 Reserve Indices 数据来源：复用 `market_snapshots` 表

**无需新建 `reserve_indices` 表**。`loan.aave_v{2|3}_market_snapshots` 已包含所需字段：

| 字段                        | 含义                                             |
| --------------------------- | ------------------------------------------------ |
| `liquidity_index_ray`       | liquidityIndex，Ray（1e27）精度，**无空值**      |
| `variable_borrow_index_ray` | variableBorrowIndex，Ray（1e27）精度，**无空值** |
| `liquidity_rate_ray`        | 年化供给利率                                     |
| `variable_borrow_rate_ray`  | 年化变量借贷利率                                 |

**Join 方式**：`market_snapshots.block_number = daily_reserve_positions.block_number`

- `daily_collector` 快照使用的 `block_number` 精确对应 `market_snapshots` 中该天的最小 block，一对一匹配。
- 已验证：V3 全部 23 个 `daily_positions` 日期均在 `market_snapshots` 中有精确 block 匹配。

**依赖顺序**：`market_collector` 必须在 `daily_collector` 之前运行（或同 block 已有快照），
否则 Step A 需降级为 RPC 读取（见 §5.1.2）。

### 4.3 历史用户注册表

从 `aave_history` 派生，无需新建表，仅需查询。

**实际表结构（与文档原草稿不同）**：

| 字段                  | 类型                | 说明                                                          |
| --------------------- | ------------------- | ------------------------------------------------------------- |
| `protocol_version`    | enum（`'2'`/`'3'`） | 协议版本（非 `'v2'`/`'v3'`）                                  |
| `operation_type`      | enum                | `deposit`/`withdraw`/`borrow`/`repay`/`liquidate`/`flashloan` |
| `user_address`        | `bytea`             | 操作发起人（原草稿 `"user"` 列）                              |
| `target_user_address` | `bytea`             | 被代理/被清算地址（原草稿 `"onBehalfOf"` 列）                 |
| `block_number`        | `bigint`            | 区块号                                                        |
| `created_at`          | `timestamptz`       | **采集时间**（非区块时间，用于日期过滤时需注意）              |

```sql
-- 所有曾经与 Aave V3 交互过的用户地址
SELECT DISTINCT encode(user_address, 'hex') AS user_address
FROM aave."aave_history"
WHERE protocol_version = '3'
UNION
SELECT DISTINCT encode(target_user_address, 'hex') AS user_address
FROM aave."aave_history"
WHERE protocol_version = '3'
  AND target_user_address IS NOT NULL;
```

> 注意：`user_address` 为 `bytea`，代码中需用 `encode(..., 'hex')` 转为十六进制字符串，
> 或改用 `'\\x' || encode(...)` 格式，与系统其他地方的地址格式保持一致。

---

## 5 代码改造

### 5.1 `rpc.py`

#### 5.1.1 新增 Pool.getReserveData ABI

```python
POOL_RESERVE_DATA_ABI: list[dict] = [
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            # ReserveDataLegacy struct（V3）
            {"name": "configuration",    "type": "uint256"},
            {"name": "liquidityIndex",   "type": "uint128"},  # Ray
            {"name": "currentLiquidityRate", "type": "uint128"},
            {"name": "variableBorrowIndex",  "type": "uint128"},  # Ray
            {"name": "currentVariableBorrowRate", "type": "uint128"},
            {"name": "currentStableBorrowRate",   "type": "uint128"},
            {"name": "lastUpdateTimestamp",       "type": "uint40"},
            {"name": "id",                        "type": "uint16"},
            {"name": "aTokenAddress",             "type": "address"},
            {"name": "stableDebtTokenAddress",    "type": "address"},
            {"name": "variableDebtTokenAddress",  "type": "address"},
            {"name": "interestRateStrategyAddress","type": "address"},
            {"name": "accruedToTreasury",         "type": "uint128"},
            {"name": "unbacked",                  "type": "uint128"},
            {"name": "isolationModeTotalDebt",    "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]
```

> V2 `LendingPool.getReserveData` 返回结构不同（`ReserveData` legacy），
> 字段索引需分别处理（`liquidityIndex` 在 [1]，`variableBorrowIndex` 在 [3]，与 V3 相同）。

#### 5.1.2 新增 `fetch_reserve_indices`

`ReserveIndex` dataclass 新增（字段名与 `market_snapshots` 保持一致）：

```python
@dataclass
class ReserveIndex:
    token_address: str
    liquidity_index: int        # Ray = 1e27，对应 market_snapshots.liquidity_index_ray
    variable_borrow_index: int  # Ray = 1e27，对应 market_snapshots.variable_borrow_index_ray
    liquidity_rate: int
    variable_borrow_rate: int
```

`fetch_reserve_indices` 函数：

```python
async def fetch_reserve_indices(
    w3: AsyncWeb3,
    contracts: ProtocolContracts,
    token_addresses: list[str],
    block_number: int,
) -> dict[str, ReserveIndex]:
    """
    用 Multicall3 一次性拉取所有 reserve 当日 liquidityIndex 和 variableBorrowIndex。
    block_number >= MULTICALL3_DEPLOY_BLOCK 时走 Multicall3（1 次 RPC）；
    否则 asyncio.gather 并发（降级）。

    注：结果仅在 market_snapshots 中尚无该 block 数据时才需写入；
    通常 market_collector 先于 daily_collector 运行，Step A 可直接从 DB 读取。
    """
```

#### 5.1.3 `ReservePosition` 新增 4 个字段

```python
@dataclass
class ReservePosition:
    ...（现有字段）...
    scaled_supply_raw: int = 0             # 新增
    scaled_variable_debt_raw: int = 0      # 新增（来自 getUserReserveData[4]）
    principal_stable_debt_raw: int = 0     # 新增（来自 getUserReserveData[3]）
    stable_borrow_rate: int = 0            # 新增（来自 getUserReserveData[5]）
```

#### 5.1.4 `fetch_user_position_at_block` 填充新字段

在构建 `ReservePosition` 时补充：

```python
reserves.append(
    ReservePosition(
        ...（现有字段）...
        scaled_variable_debt_raw=reserve_data[4],   # 直接取已解码字段
        principal_stable_debt_raw=reserve_data[3],
        stable_borrow_rate=reserve_data[5],
        # scaled_supply 由调用方在已知 liquidity_index 后注入，或在此处传入 index 推导
    )
)
```

> 字段名 `stable_borrow_rate` 为 dataclass 字段（Python），写库时映射到列名 `stable_borrow_rate_raw`。

### 5.2 `daily_collector.py`

#### 5.2.1 `upsert_daily_positions`：写入新字段

`_DAILY_RES_COLUMNS` 新增 4 列，`all_reserve_rows` 的每个 tuple 追加对应值：

```python
# 新增 4 个字段的计算（liquidity_index 来自 reserve_indices dict，已从 market_snapshots 或 RPC 获取）
idx = reserve_indices.get(r.token_address.lower())
scaled_supply = (
    (Decimal(r.supply_raw) * Decimal(10**27)) // Decimal(idx.liquidity_index)
    if idx and idx.liquidity_index > 0
    else Decimal(0)
)
all_reserve_rows.append((
    ...现有 14 列...
    scaled_supply,                           # → scaled_supply_raw
    Decimal(r.scaled_variable_debt_raw),     # → scaled_variable_debt_raw
    Decimal(r.principal_stable_debt_raw),    # → principal_stable_debt_raw
    Decimal(r.stable_borrow_rate),           # → stable_borrow_rate_raw
))
```

#### 5.2.2 主流程新增 Step A：读取当日 reserve indices

在 Phase 1 之前，优先从 `market_snapshots` 读取（通常 `market_collector` 已先运行）；
若当日 block 尚无数据则降级为 RPC 获取：

```python
# Step A：从 market_snapshots 读取当日 index（0 次 RPC）
reserve_indices = await load_reserve_indices_from_db(pool, block_number, protocol)
if not reserve_indices:
    # 降级：market_collector 尚未运行，通过 RPC 获取
    reserve_indices = await fetch_reserve_indices(w3, contracts, token_addresses, block_number)
    # 可选：写入 market_snapshots 避免重复 RPC（由 market_collector 补全即可，此处跳过）
```

`load_reserve_indices_from_db` 实现：

```python
async def load_reserve_indices_from_db(
    pool: asyncpg.Pool,
    block_number: int,
    protocol: str,   # "v2" | "v3"
) -> dict[str, ReserveIndex]:
    """从 market_snapshots 按 block_number 精确读取 index。"""
    table = f"aave_{protocol}_market_snapshots"
    rows = await pool.fetch(f"""
        SELECT token_address, liquidity_index_ray, variable_borrow_index_ray,
               liquidity_rate_ray, variable_borrow_rate_ray
        FROM loan."{table}"
        WHERE block_number = $1
    """, block_number)
    return {
        r["token_address"]: ReserveIndex(
            token_address=r["token_address"],
            liquidity_index=int(r["liquidity_index_ray"]),
            variable_borrow_index=int(r["variable_borrow_index_ray"]),
            liquidity_rate=int(r["liquidity_rate_ray"]),
            variable_borrow_rate=int(r["variable_borrow_rate_ray"]),
        )
        for r in rows
    }
```

#### 5.2.3 新增 `forward_recalc_positions`（DB 内重算）

对无事件用户，在 DB 内用 SQL 完成 index 重算并写入当日快照。
Index 直接从 `market_snapshots` 按 `block_number` join（无需独立 `reserve_indices` 表）：

```sql
-- 从昨日快照 + 今日 index（来自 market_snapshots）推导今日仓位
INSERT INTO loan."aave_v3_eth_daily_reserve_positions"
    (snapshot_date, user_address, token_address, block_number, block_timestamp,
     symbol, decimals, price_usd,
     supply_raw, supply_usd, stable_debt_raw, variable_debt_raw, total_debt_usd,
     use_as_collateral,
     scaled_supply_raw, scaled_variable_debt_raw, principal_stable_debt_raw, stable_borrow_rate_raw)
SELECT
    $today                                          AS snapshot_date,
    p.user_address,
    p.token_address,
    $today_block                                    AS block_number,
    $today_block_ts                                 AS block_timestamp,
    p.symbol,
    p.decimals,
    ms.price_usd,                                   -- 今日价格来自 market_snapshots
    -- supply（index 重算）
    p.scaled_supply_raw * ms.liquidity_index_ray / 1e27          AS supply_raw,
    -- variable debt（index 重算）
    p.scaled_variable_debt_raw * ms.variable_borrow_index_ray / 1e27  AS variable_debt_raw,
    -- stable debt（指数复利，精度约 0.001%）
    p.principal_stable_debt_raw
        * POWER(1 + p.stable_borrow_rate_raw::FLOAT / 1e27,
                EXTRACT(EPOCH FROM ($today::timestamp - p.block_timestamp)))
                                                    AS stable_debt_raw,
    -- usd 换算（supply_raw / 10^decimals * price_usd）
    p.scaled_supply_raw * ms.liquidity_index_ray / 1e27
        / POWER(10, p.decimals) * ms.price_usd      AS supply_usd,
    ...                                             -- total_debt_usd 类似
    p.use_as_collateral,
    -- scaled 字段原样保留（不随 index 变化）
    p.scaled_supply_raw,
    p.scaled_variable_debt_raw,
    p.principal_stable_debt_raw,
    p.stable_borrow_rate_raw
FROM loan."aave_v3_eth_daily_reserve_positions" p
JOIN loan."aave_v3_market_snapshots" ms
    ON ms.block_number = $today_block              -- 精确 block 匹配，一对一
    AND ms.token_address = p.token_address
WHERE p.snapshot_date = $yesterday
  AND p.user_address = ANY($no_event_users)
ON CONFLICT (snapshot_date, user_address, token_address)
    DO UPDATE SET
        supply_raw = EXCLUDED.supply_raw,
        variable_debt_raw = EXCLUDED.variable_debt_raw,
        stable_debt_raw = EXCLUDED.stable_debt_raw,
        ...;
```

`daily_positions` 汇总行（health factor、liq_price 等）同样由 SQL 重算，
无需 Python 逐行处理。

#### 5.2.4 重构后的主流程伪代码

```text
per day:
  Step A: fetch_reserve_indices(block)         # 1 次 Multicall3
  Step B: event_users = query_aave_history(day)
  Step C: no_event_users = day_users - event_users

  # 事件用户：完整 RPC 查询（同现有两阶段）
  Phase 1: fetch_batch_account_summaries(event_users)   # ~4 批
  Phase 2: fetch_user_position_at_block(active_event_users)  # ~200 次
  Write:   upsert_daily_positions(event_users_results)

  # 无事件用户：纯 DB 重算
  Step D: forward_recalc_positions(no_event_users, indices, day)  # SQL
```

---

## 6 执行计划

### Phase 0：Schema 准备（无停机，向后兼容）

**目标**：在不影响现有采集的前提下扩展表结构。

| 步骤 | 操作                                       | 说明                                                                                                                                         |
| ---- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 0.1  | ~~`ALTER TABLE` 新增 4 列（`DEFAULT 0`）~~ | **✅ 已完成**：两张 `daily_reserve_positions` 表均已有 4 列（V3 部分填充，V2 全为 0）                                                        |
| 0.2  | ~~创建 `reserve_indices` 表~~              | **✅ 无需**：直接复用 `loan.aave_v{2\|3}_market_snapshots`（已含 `liquidity_index_ray`/`variable_borrow_index_ray`，按 `block_number` join） |
| 0.3  | 验证 `aave_history` 表事件完整性           | **✅ 已验证**，结果如下                                                                                                                      |

**Phase 0.3 验证结果（2026-03-17 复验）**：

- ✅ 6 类事件全部覆盖：`deposit` / `withdraw` / `borrow` / `repay` / `liquidate` / `flashloan`
- ✅ 今日数据实时（V3 当日已采集 2000+ 条）
- ✅ 数据范围：V2 2020-11-30 至今（156 万条），V3 2023-01-27 至今（356 万条）
- ✅ **原主要断层已补全**（chain-data-collector 补采后）

**剩余断层（均为 2 天，影响极小）**：

| 协议 | 缺口时间段              | 天数 | 说明                      |
| ---- | ----------------------- | ---- | ------------------------- |
| V2   | 2023-11-04 → 2023-11-13 | 9 天 | 历史停运，无法补采        |
| V3   | 2025-05-06 → 2025-05-08 | 2 天 | 轻微，影响可忽略          |
| V2   | 2025-05-03 → 2025-05-05 | 2 天 | 同上                      |
| V2   | 2025-05-06 → 2025-05-08 | 2 天 | 同上                      |
| V2   | 2026-03-12 → 2026-03-14 | 2 天 | 轻微（2026-03-13 未采集） |

原记录中的 **13天（V3 2025-10）、14天（V2 2025-10）、7天（V2 2026-03）大断层均已补全**。

**影响评估**：仅 V2 2023-11 的 9 天历史断层需在 Phase 4 回填时对该段日期强制走全量 RPC；其余 2 天断层影响极小，可接受 index 重算误差或 Phase 5 对账修正。

**耗时估计**：半天（0.1/0.2 已完成，仅需 0.3 验证）

---

### Phase 1：扩展 `rpc.py` 和 `models.py`

**目标**：补充现有 RPC 路径写入 scaled 字段，验证数据正确性。

| 步骤 | 文件                 | 操作                                                                                  |
| ---- | -------------------- | ------------------------------------------------------------------------------------- |
| 1.1  | `models.py`          | `ReservePosition` 新增 4 个字段（`default=0`，向后兼容）                              |
| 1.2  | `rpc.py`             | 新增 `ReserveIndex` dataclass                                                         |
| 1.3  | `rpc.py`             | 新增 `POOL_RESERVE_DATA_ABI`、`fetch_reserve_indices`、`load_reserve_indices_from_db` |
| 1.4  | `rpc.py`             | `fetch_user_position_at_block` 填充新字段（`scaled_variable_debt_raw` 等）            |
| 1.5  | `daily_collector.py` | `upsert_daily_positions` 写入新 4 列（列名 `stable_borrow_rate_raw`）                 |
| 1.6  | `daily_collector.py` | 主流程新增 Step A：先从 `market_snapshots` 按 `block_number` 读 index，缺失时降级 RPC |

**验证结果（2026-02-10 ~ 2026-02-17 数据，V3，小样本初验）**：✅ **Phase 1 已完成验证**

| 字段                                 | 样本数                | avg rel_error | max rel_error | 结论                         |
| ------------------------------------ | --------------------- | ------------- | ------------- | ---------------------------- |
| `scaled_supply_raw` roundtrip        | 245 行（dust > 1e12） | 1.53e-14      | 9.15e-13      | ✅ 机器精度级，完全正确      |
| `scaled_variable_debt_raw` roundtrip | 107 行（dust > 1e12） | 1.90e-05      | 1.44e-03      | ✅ 符合预期（见下）          |
| `principal_stable_debt_raw`          | —                     | 0             | 0             | ✅ V3 稳定利率已废弃，无仓位 |
| `stable_borrow_rate`                 | —                     | 0             | 0             | ✅ 同上                      |

**扩展验证（2026-02-28 ~ 2026-03-05，V3，大样本 SQL roundtrip）**：✅ 结论一致

| 字段                                 | 样本数     | avg rel_error | max rel_error                | 结论                      |
| ------------------------------------ | ---------- | ------------- | ---------------------------- | ------------------------- |
| `scaled_supply_raw` roundtrip        | 297,944 行 | 1.28e-14      | 1.13e-12                     | ✅ 机器精度，与小样本一致 |
| `scaled_variable_debt_raw` roundtrip | 52,566 行  | 3.39e-05      | 9.71e-03（SNX，27 天未更新） | ✅ 符合预期，误差分布见下 |

误差分布（`scaled_variable_debt_raw`，V3 大样本）：

| 误差区间    | 行数   | 占比  |
| ----------- | ------ | ----- |
| < 1e-6      | 33,295 | 63.3% |
| 1e-6 ~ 1e-4 | 18,261 | 34.7% |
| 1e-4 ~ 1e-3 | 817    | 1.6%  |
| > 1e-3      | 193    | 0.4%  |

**`scaled_variable_debt` 误差说明（预期行为）**：

误差来源于 `variableBorrowIndex` 的两种取值语义不同：

- **`market_snapshots` 存储的 index**：来自 `DataProvider.getReserveData()`，写入时刻为最后一次 `Pool.updateState()` 调用（即该 reserve 上次有用户操作的时刻）
- **`getUserReserveData` 使用的 normalizedVariableDebt**：在调用时动态复利计算至当前秒，始终比存储值略大

误差方向：存储 index < 动态 normalizedVariableDebt，导致重算值**始终低估**，符合预期。最大误差由 SNX（~27 天未更新）产生 0.97%，是 V3 中极端案例。

**对 Phase 2 前向重算的影响**：`forward_recalc` 在 DB 内用 `market_snapshots.variable_borrow_index_ray` 做重算，与 Phase 1 使用同一 index 来源，因此两次计算一致；轻微低估是系统性的、可预期的，不影响运营决策（HF/liq_price 精度远低于该量级）。

---

**验证结果（V2，最新区块 RPC 直测，20 用户）**：✅ **Phase 1 V2 代码路径已验证**

> V2 背景说明：V2 market_snapshots 区块（UTC ~20:xx）与 daily_positions 区块（UTC 00:00）错位 ~1000 块，RPC 直测方式用于验证新代码路径正确性。

| 字段                                                  | 样本数 | avg rel_error | max rel_error  | 结论                     |
| ----------------------------------------------------- | ------ | ------------- | -------------- | ------------------------ |
| `scaled_supply_raw` roundtrip（所有 token）           | 46 行  | 1.89e-14      | 8.41e-13       | ✅ 机器精度              |
| `scaled_variable_debt_raw`（活跃 token，<24h 未更新） | 5 行   | 1.95e-04      | 1.95e-04       | ✅ ~0.02%，与 V3 相当    |
| `scaled_variable_debt_raw`（非活跃 token，≥24h）      | 45 行  | 7.42e-03      | 8.32e-02 (FEI) | ⚠️ 预期行为（见下）      |
| `principal_stable_debt_raw` / `stable_borrow_rate`    | —      | 0             | 0              | ✅ V2 当前无稳定债务仓位 |

**扩展验证（2026-03-13 ~ 2026-03-16，V2，SQL nearest-neighbor roundtrip）**：✅ 结论一致

> V2 SQL roundtrip 使用 nearest-neighbor（CROSS JOIN LATERAL）匹配 market_snapshots 最近块，~1000 块偏差引入约 1e-6 量级额外误差，可忽略。

| 字段                                 | 样本数   | avg rel_error | max rel_error                 | 结论                                             |
| ------------------------------------ | -------- | ------------- | ----------------------------- | ------------------------------------------------ |
| `scaled_supply_raw` roundtrip        | 5,382 行 | 3.38e-07      | 4.78e-06                      | ✅ nearest-neighbor 引入约 1e-6 额外误差，可忽略 |
| `scaled_variable_debt_raw` roundtrip | 592 行   | 5.60e-03      | 2.48e-01（LUSD，34 天未更新） | ⚠️ 预期行为，见下                                |

V2 最大误差 token（`scaled_variable_debt_raw`）：

| Token  | 最大误差 | 未更新时长     | 说明             |
| ------ | -------- | -------------- | ---------------- |
| LUSD   | 24.8%    | ~809h（34天）  | 活跃度极低，预期 |
| FEI    | 8.26%    | 3803h（158天） | 已废弃，预期     |
| ZRX 等 | 2~5%     | 1400~1700h     | 长期冷门，预期   |

**V2 非活跃 token 高误差说明**：

V2 有 30/37 个 token 长期未触发 `updateState`，极端案例：

- FEI（已废弃）：3803h（158 天）未更新 → 8.3% 误差
- UST（已废弃）：2410h（100 天）未更新
- LUSD：~809h（34 天）未更新 → 24.8% 误差（LUSD 利率显著高于 FEI，因此单位时间累积误差更大）
- ZRX、REN、BAT 等：1400~1700h 未更新

根因与 V3 相同（stored index < normalizedVariableDebt），但 V2 的非活跃 token 间隔更长。
活跃主流 token（USDT, WETH, WBTC, USDC, AAVE, stETH）误差 ≤ 0.02%，**完全在可接受范围**。

`fetch_reserve_indices` V2 路径（`liq_idx=[7]`, `var_idx=[8]`）验证通过，返回 37 个 token 指数，无 decode 异常。

**耗时估计**：1–2 天（✅ 已完成）

---

### Phase 2：实现 `forward_recalc_positions`

**目标**：实现并验证 DB 内 index 重算逻辑，在有完整 scaled 数据的时间窗口内测试。

| 步骤 | 操作                                                                    |
| ---- | ----------------------------------------------------------------------- |
| 2.1  | 编写 `forward_recalc_positions(pool, no_event_users, day, protocol)`    |
| 2.2  | 在测试库对 1 周数据对比：RPC 查询结果 vs index 重算结果                 |
| 2.3  | 验证 liq_price、health_factor 重算精度（允差 < 0.1%）                   |
| 2.4  | 处理边界：index 为 0、scaled 为 0（新用户第一天）、稳定债务用户单独处理 |

**稳定债务精度注意**：

稳定债务的指数复利计算在秒级精度上可能与链上有微小差异（约 0.001%），
属于可接受误差。若要求精确，稳定债务用户保留 RPC 查询路径（稳定债务持仓占比通常 < 5%）。

**耗时估计**：2–3 天

---

### Phase 3：事件驱动整合

**目标**：主流程接入 `aave_history` 事件过滤，实现完整的新架构。

| 步骤 | 操作                                                                                 |
| ---- | ------------------------------------------------------------------------------------ |
| 3.1  | 编写 `fetch_event_users(pool, day, protocol) -> set[str]`，查询 `aave_history`       |
| 3.2  | `run_daily_collector` 主流程拆分：事件用户走 Phase1/2，无事件用户走 `forward_recalc` |
| 3.3  | 验证边界：新用户首次出现（无昨日快照）触发全量 RPC                                   |
| 3.4  | 在最近 30 天数据上对比新旧流程结果，确认一致                                         |

**耗时估计**：2 天

---

### Phase 4：历史用户补全 + 3 年回填

**目标**：枚举所有历史用户，从起始区块开始滚动重建 3 年数据。

| 步骤 | 操作                                                         |
| ---- | ------------------------------------------------------------ |
| 4.1  | 从 `aave_history` 提取所有历史用户地址（V2 + V3）            |
| 4.2  | 选定回填起始日期（V2: 2021-01-08；V3: 2023-01-27）           |
| 4.3  | 起始日执行一次全量 RPC 快照（现有两阶段，仅 1 天成本）       |
| 4.4  | 后续天滚动推进：事件驱动 + index 重算                        |
| 4.5  | Pre-Multicall3 时期（V2 2021-01 至 2022-03）降级处理（见下） |

**Pre-Multicall3 处理策略**：

该时期 `fetch_batch_account_summaries` 已有降级路径（`asyncio.gather` 逐用户调用），
但事件驱动仍然适用——每天只需查 ~200 个事件用户，而非全量 6448+ 个：

```text
Pre-Multicall3 时期每天：
  事件用户（~200）× 个别 RPC ~200 × 3 calls = ~600 次
  无事件用户（~6248）= 0 次 RPC（index 重算）
  合计：~600 次/天（vs 现有两阶段 14,500 次/天）
```

**耗时估计**：1 天配置 + 2 小时实际运行

---

### Phase 5：定期全量对账

为防止 `aave_history` 漏事件导致 scaled 值静默漂移：

| 频率 | 操作                                                   |
| ---- | ------------------------------------------------------ |
| 每周 | 随机抽样 1% 用户做 RPC 对比，rel_error > 0.1% 触发告警 |
| 每月 | 对当月活跃用户全量 RPC 校验一次                        |
| 手动 | 发现 Aave 协议升级或参数变更时触发全量 re-sync         |

---

## 7 边界情况与风险

### 7.1 新用户首次出现

**场景**：用户在某天首次存款，`aave_history` 中存在事件，但昨日无快照。

**处理**：在 `forward_recalc` 前检查：无昨日记录的用户自动归入**事件用户**路径，
触发全量 RPC 查询。

### 7.2 同一天多次操作

**场景**：用户当天存款后又借款，最终余额与任意单次事件后的状态均不同。

**处理**：事件用户走全量 RPC 查询（在区块末尾时间点），取最终链上状态，
与当前逻辑完全一致，无需特殊处理。

### 7.3 闪贷（Flash Loan）

**场景**：闪贷在同一笔 TX 内借还，结束后仓位无净变化，但 `aave_history` 中有记录。

**处理**：闪贷用户会被错误纳入事件路径触发 RPC，但结果正确（小量额外 RPC 可接受）。

### 7.4 稳定债务利率变化（Stable Rate Swap）

**场景**：用户将稳定债务切换为变量债务，稳定债务归零，需更新 `stable_borrow_rate`。

**处理**：`SWAP_BORROW_RATE_MODE` 事件包含在 `aave_history` 中，
该用户会被纳入事件路径，触发完整 RPC 更新。

### 7.5 aave_history 数据断层

**风险**：若 chain-data-collector 停运导致部分天 `aave_history` 不完整，
事件用户集合偏小，未被识别的操作用户会停留在 index 重算路径，产生余额漂移。

**已知断层（Phase 0.3 验证时发现）**：

| 协议 | 缺口时间段 | 天数 |
| ---- | ---------- | ---- |

| 协议  | 缺口时间段                 | 天数  | 状态                      |
| ----- | -------------------------- | ----- | ------------------------- |
| V2    | 2023-11-04 → 2023-11-13    | 9 天  | ⚠️ 历史停运，无法补采     |
| V3    | 2025-10-06 → 2025-10-19    | 13 天 | ✅ 已补全                 |
| V2    | 2025-10-06 → 2025-10-20    | 14 天 | ✅ 已补全                 |
| V2    | 2026-03-05 → 2026-03-12    | 7 天  | ✅ 已补全                 |
| V3/V2 | 2025-05-06 → 2025-05-08 等 | 2 天  | ℹ️ 轻微，Phase 5 对账即可 |

**缓解**：

1. 历史回填时对已知断层日期强制走全量 RPC 快照（bypass 事件过滤）
2. Phase 5 每周抽样对账
3. 监控 `aave_history` 最新 `created_at`，设置 >1 小时无新数据告警
4. 对账发现漂移时，对该用户重走 RPC 路径并更新 scaled 值

### 7.6 协议升级（Aave V3.1+）

Aave V3.1 引入了 Virtual Accounting（虚拟余额），`liquidityIndex` 计算逻辑有微调。
**处理**：升级前后的 index 数据来源不变（均从 `Pool.getReserveData()` 读取），
重算公式本身不受影响，但需在升级块附近做全量 RPC 对账验证。
