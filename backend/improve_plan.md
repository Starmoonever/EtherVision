# collect-daily 性能改进计划

## 背景

`collect-daily` 命令对每个用户需要向 Archive 节点发送约 21 次 `eth_call`
（1×`getUserAccountData` + N×`getUserReserveData`，V3 约 20 个 token）。
以默认并发度 20、2000 用户计算，最多同时有 **400 个 eth_call** 飞向节点，
且 Archive 节点通常有严格的 RPC 速率限制，这是主要瓶颈。

---

## 改进项列表

### ✅ Step 1：Multicall3 批量化 `getUserReserveData`（最高优先级）

**文件：** `aave_crawler/rpc.py`

**现状：** 每用户 N 次独立 `eth_call`（asyncio.gather 并发但仍 N 个 round-trip）

```text
getUserAccountData (1 RPC)
getUserReserveData × 20 (20 RPCs, concurrent)
────────────────────────────────────────────
合计：21 次 RPC / 用户
```

**目标：** 用 Multicall3 将 N 次 `getUserReserveData` 合并为 1 次 `eth_call`

```text
getUserAccountData (1 RPC)
aggregate3([getUserReserveData×20]) (1 RPC, Multicall3)
────────────────────────────────────────────────────────
合计：2 次 RPC / 用户（减少 ~10×）
```

**实施细节：**

- Multicall3 合约地址：`0xcA11bde05977b3631167028862bE2a173976CA11`（Ethereum Mainnet 部署区块 `14_353_601`，2022-03-09）
- 历史块 `< 14_353_601` 自动降级回原来的 `asyncio.gather` 路径（覆盖早期 V2 数据）
- 同时更新 `fetch_user_position`（实时爬虫）和 `fetch_user_position_at_block`（历史回放）

**预期收益：** 对于 block ≥ 14_353_601 的请求，RPC 总量减少约 10×，吞吐量线性提升。

**状态：** ✅ 已完成

---

### ⬜ Step 2：预取 `block_timestamps` + `fetch_block_prices`，消除每天串行等待

**文件：** `aave_crawler/daily_collector.py`

**现状：**

```python
for day, block_number in zip(days, block_numbers):
    raw_block = await w3.eth.get_block(block_number)      # 串行
    block_prices = await fetch_block_prices(...)           # 串行
    # ... 处理用户
```

**目标：** 在进入用户处理循环之前，一次性并行预取所有天的区块元信息和价格：

```python
metas = await asyncio.gather(*[
    asyncio.gather(
        w3.eth.get_block(bn),
        fetch_block_prices(w3, contracts, token_addresses, bn)
    )
    for bn in block_numbers
])
```

**预期收益：** 消除 `len(days)` 次串行网络等待，在多天批量追补时收益显著。

**状态：** ✅ 已完成

---

### ⬜ Step 3：DB 写入改为双缓冲（pipeline 不中断）

**文件：** `aave_crawler/daily_collector.py`

**现状：** 单 `db_task` 槽，填满 batch 后必须等待上一个 db_task 完成才能提交新批次：

```python
if len(pending) >= batch_size:
    if db_task is not None:
        await db_task          # 此处阻塞 RPC 结果处理
    db_task = asyncio.ensure_future(upsert_daily_positions(...))
```

**目标：** 维护最多 2 个并发写入任务，RPC 与 DB 写入不互相等待：

```python
MAX_DB_TASKS = 2
pending_db_tasks: list[asyncio.Task] = []

if len(pending) >= batch_size:
    done_tasks = [t for t in pending_db_tasks if t.done()]
    pending_db_tasks = [t for t in pending_db_tasks if not t.done()]
    if len(pending_db_tasks) >= MAX_DB_TASKS:
        await pending_db_tasks[0]
        pending_db_tasks.pop(0)
    if not dry_run:
        pending_db_tasks.append(asyncio.ensure_future(upsert_daily_positions(...)))
    pending.clear()
```

**状态：** ⬜ 待实施

---

### ⬜ Step 4：`--skip-existing` 改为批量预加载已完成用户

**文件：** `aave_crawler/daily_collector.py`

**现状：** 每天单独查一次 DB，获取当天已完成用户：

```python
collected = await get_collected_users(pool, protocol, day)
```

**目标：** 在主循环前一次性查所有待处理天：

```python
if skip_existing:
    rows = await pool.fetch(
        f'SELECT snapshot_date, user_address FROM loan."{tables.positions}"'
        f' WHERE snapshot_date = ANY($1)',
        days
    )
    collected_by_day = defaultdict(set)
    for r in rows:
        collected_by_day[r["snapshot_date"]].add(r["user_address"])
```

**状态：** ⬜ 待实施

---

### ⬜ Step 5：每日采集后回写 `eth_block_timestamps`

**文件：** `aave_crawler/daily_collector.py`

**现状：** 通过二分搜索找到的区块号没有写回 `eth_block_timestamps` 缓存表，
导致下次运行相同日期范围时仍需重新搜索。

**目标：** 在主循环后批量 upsert 所有 `(block_number, block_timestamp)` 对：

```python
from .market_collector import upsert_block_timestamps
await upsert_block_timestamps(pool, list(zip(block_numbers, block_timestamps)))
```

**状态：** ⬜ 待实施
