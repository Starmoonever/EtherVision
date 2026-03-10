"""临时调试脚本：检查指定地址的 aave_history liquidation 记录
与 position_snapshot_cache 的差异，以及 seen_blocks 去重逻辑的影响。
"""

import asyncio
import sys
from collections import Counter

sys.path.insert(0, ".")

ADDR = "0x1111567E0954E74f6bA7c4732D534e75B81DC42E"
PROTOCOL = "v3"


async def main():
    from aave_crawler.config import load_config
    from aave_crawler.db import create_pool

    cfg = load_config()
    pool = await create_pool(cfg.postgres)

    # ── 1. aave_history 原始数据 ────────────────────────────────────────────
    rows = await pool.fetch(
        """
        SELECT
            operation_type::text                     AS op,
            lower(encode(tx_hash, 'escape'))         AS tx_hash,
            block_number,
            lower(encode(user_address, 'escape'))    AS user_addr,
            CASE WHEN target_user_address IS NOT NULL
                 THEN lower(encode(target_user_address, 'escape'))
                 ELSE NULL END                       AS target_user,
            protocol_version::text                   AS proto
        FROM aave.aave_history
        WHERE protocol_version::text = $3
          AND (
            lower(encode(user_address, 'escape')) = lower($1)
            OR (
              target_user_address IS NOT NULL
              AND lower(encode(target_user_address, 'escape')) = lower($1)
            )
          )
        ORDER BY block_number ASC
        """,
        ADDR.lower(),
        ADDR.lower(),
        PROTOCOL[-1],  # $1, $2(unused here), $3
    )

    # fetch 不支持多次 $1，改写：
    rows = await pool.fetch(
        """
        SELECT
            operation_type::text                     AS op,
            lower(encode(tx_hash, 'escape'))         AS tx_hash,
            block_number,
            lower(encode(user_address, 'escape'))    AS user_addr,
            CASE WHEN target_user_address IS NOT NULL
                 THEN lower(encode(target_user_address, 'escape'))
                 ELSE NULL END                       AS target_user,
            protocol_version::text                   AS proto
        FROM aave.aave_history
        WHERE protocol_version::text = $2
          AND (
            lower(encode(user_address, 'escape')) = lower($1)
            OR (
              target_user_address IS NOT NULL
              AND lower(encode(target_user_address, 'escape')) = lower($1)
            )
          )
        ORDER BY block_number ASC
        """,
        ADDR.lower(),
        PROTOCOL[-1],
    )

    print("=" * 60)
    print(f"aave_history 原始行数: {len(rows)}")
    op_counts = Counter(r["op"] for r in rows)
    print("operation_type 分布:", dict(op_counts))

    liq_rows = [r for r in rows if "liquidat" in r["op"].lower()]
    print(f"\nliquidationcall 共 {len(liq_rows)} 条:")
    for r in liq_rows:
        is_target = r["target_user"] and r["target_user"].lower() == ADDR.lower()
        print(
            f"  block={r['block_number']}  tx={r['tx_hash'][:20]}..."
            f"  role={'被清算方(target)' if is_target else '清算发起方(user)'}"
        )

    # ── 2. 模拟 service.py 中的 seen_blocks 去重逻辑 ───────────────────────
    # 先查 cached_map（简化：用 tx_hash set 代替）
    cached_rows = await pool.fetch(
        """
        SELECT tx_hash FROM loan.position_snapshot_cache
        WHERE user_address = lower($1) AND protocol = $2
        """,
        ADDR.lower(),
        PROTOCOL,
    )
    cached_set = {r["tx_hash"] for r in cached_rows}
    print(f"\nposition_snapshot_cache 已有 {len(cached_set)} 条")

    # 模拟去重
    seen_blocks: dict[int, dict] = {}
    for r in rows:
        bn = r["block_number"]
        th = r["tx_hash"]
        if bn not in seen_blocks or (th in cached_set):
            seen_blocks[bn] = dict(r)

    deduped = sorted(seen_blocks.values(), key=lambda x: x["block_number"])
    print(f"\n去重后 (seen_blocks) 共 {len(deduped)} 条")

    # 哪些 liquidationcall 被去重掉了？
    liq_tx_hashes = {r["tx_hash"] for r in liq_rows}
    deduped_tx_hashes = {r["tx_hash"] for r in deduped}
    dropped_liq = liq_tx_hashes - deduped_tx_hashes
    print(f"被去重逻辑丢弃的 liquidationcall tx: {len(dropped_liq)}")
    for th in dropped_liq:
        original = next(r for r in liq_rows if r["tx_hash"] == th)
        # 找到同一 block 里保留的那条
        kept = seen_blocks.get(original["block_number"])
        print(f"  丢弃 tx={th[:20]}... block={original['block_number']}")
        if kept:
            print(f"  保留 tx={kept['tx_hash'][:20]}... op={kept['op']}")

    # ── 3. 检查哪些 liquidationcall tx 不在 snapshot_cache 里 ──────────────
    print("\n" + "=" * 60)
    print("liquidationcall tx 在 snapshot_cache 中的状态:")
    for r in liq_rows:
        in_cache = r["tx_hash"] in cached_set
        in_deduped = r["tx_hash"] in deduped_tx_hashes
        print(
            f"  block={r['block_number']}  in_cache={in_cache}"
            f"  in_deduped={in_deduped}  op={r['op']}"
        )

    await pool.close()


asyncio.run(main())
