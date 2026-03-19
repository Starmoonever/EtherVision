"""
_explore_ch_logs.py
────────────────────────────────────────────────────────────────────────────────
探查 ClickHouse eth_defi.rrmt_logs 表结构与内容。

已确认 schema（2026-03-18）：
  Hash        FixedString(66)   tx hash，Python 返回 bytes
  BlockNumber UInt64
  Address     FixedString(42)   合约地址（lowercase，带 0x），Python 返回 bytes
  TopicHash   FixedString(66)   = topic[0]（事件签名 hash），Python 返回 bytes
  Topics      String            topic[1..N] 逗号分隔（不含 topic0）
  Data        String            ABI-encoded event data
  CreatedAt   DateTime
  Serial      UInt64
  BlockHash   FixedString(66)

用法：
    uv run python scripts/_explore_ch_logs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.clickhouse import ClickHouseClient  # noqa: E402
from aave_crawler.config import load_config  # noqa: E402

TABLE = "eth_defi.rrmt_logs"

# ERC-20 Transfer 事件签名 keccak256("Transfer(address,address,uint256)")
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Aave V3 以太坊主网 aToken 地址样本（验证 Address 字段格式）
AAVE_V3_ATOKENS = [
    "0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8",  # aWETH
    "0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c",  # aUSDC
]


def sep(title: str) -> None:
    print(f"\n{'─' * 72}\n  {title}\n{'─' * 72}")


def main() -> None:
    cfg = load_config()
    print(
        f"连接 ClickHouse：{cfg.clickhouse.host}:{cfg.clickhouse.port} / {cfg.clickhouse.database}"
    )

    with ClickHouseClient(cfg.clickhouse) as ch:
        # ── 1. 行数 & 时间范围 ────────────────────────────────────────────────
        sep("行数 & 范围")
        rows = ch.query(f"""
            SELECT count(), min(BlockNumber), max(BlockNumber),
                   min(CreatedAt), max(CreatedAt)
            FROM {TABLE}
        """)
        cnt, bn_min, bn_max, ts_min, ts_max = rows[0]
        print(f"  总行数      : {cnt:,}")
        print(f"  BlockNumber : {bn_min:,} → {bn_max:,}")
        print(f"  CreatedAt   : {ts_min} → {ts_max}")

        # ── 2. 样本行（含真实 Transfer 事件）────────────────────────────────
        sep("Transfer 事件样本行（LIMIT 3）")
        cols, samples = ch.query_with_names(f"""
            SELECT Hash, BlockNumber, Address, TopicHash, Topics, Data
            FROM {TABLE}
            WHERE TopicHash = '{TRANSFER_SIG}'
            LIMIT 3
        """)
        if samples:
            for i, row in enumerate(samples, 1):
                print(f"\n── 行 {i} ──")
                for name, val in zip(cols, row):
                    print(f"  {name:<15} = {repr(val)}")
        else:
            print("  ⚠️  未找到 Transfer 事件行，请确认 TopicHash 格式")

        # ── 3. TopicHash 存储格式探测 ────────────────────────────────────────
        sep("TopicHash 字段格式探测")
        # 尝试不同格式：带0x小写、不带0x、大写
        for fmt in (
            TRANSFER_SIG,
            TRANSFER_SIG[2:],
            TRANSFER_SIG.upper(),
            TRANSFER_SIG[2:].upper(),
        ):
            cnt_r = ch.query(f"SELECT count() FROM {TABLE} WHERE TopicHash = '{fmt}'")
            n = cnt_r[0][0]
            if n > 0:
                print(f"  ✓  TopicHash = '{fmt}'  →  {n:,} 行")
                print(
                    f"     （匹配格式：{'带0x小写' if fmt == TRANSFER_SIG else '不带0x小写' if fmt == TRANSFER_SIG[2:] else '带0x大写' if fmt == TRANSFER_SIG.upper() else '不带0x大写'}）"
                )
                break
        else:
            print("  ⚠️  所有格式均无匹配，请检查 ClickHouse 原始值")
            raw = ch.query(f"SELECT TopicHash FROM {TABLE} LIMIT 5")
            for r in raw:
                print(f"    原始值: {repr(r[0])}")

        # ── 4. Transfer 事件中 Address 格式验证（aToken） ───────────────────
        sep("Address 字段格式验证（用已知 aToken 地址）")
        for atoken in AAVE_V3_ATOKENS:
            for fmt in (atoken, atoken[2:], atoken.upper(), atoken[2:].upper()):
                cnt_r = ch.query(
                    f"SELECT count() FROM {TABLE} "
                    f"WHERE TopicHash = '{TRANSFER_SIG}' AND Address = '{fmt}'"
                )
                n = cnt_r[0][0]
                if n > 0:
                    print(f"  ✓  {atoken}  →  {n:,} 行  (存储格式: '{fmt}')")
                    break
            else:
                print(f"  ✗  {atoken}  →  0 行（所有格式均无匹配）")

        # ── 5. Transfer Topics 字段格式（from/to 地址提取） ─────────────────
        sep("Topics 字段格式（from/to 地址）")
        sample = ch.query(f"""
            SELECT Topics
            FROM {TABLE}
            WHERE TopicHash = '{TRANSFER_SIG}'
              AND Address = '{AAVE_V3_ATOKENS[0]}'
            LIMIT 3
        """)
        if sample:
            for r in sample:
                topics_str = r[0]
                parts = topics_str.split(",")
                print(f"  Topics 原始值 : {topics_str!r}")
                print(f"  split 结果   : {parts}")
                print(f"  parts 数量   : {len(parts)}")
                print()
        else:
            print("  ⚠️  无 aWETH Transfer 样本，改用全局 Transfer 样本")
            sample = ch.query(
                f"SELECT Topics FROM {TABLE} WHERE TopicHash = '{TRANSFER_SIG}' LIMIT 3"
            )
            for r in sample:
                print(f"  Topics: {r[0]!r}")

        # ── 6. Transfer 总量统计 ─────────────────────────────────────────────
        sep("Transfer 事件规模（TOP-10 aToken 地址）")
        top_atokens = ch.query(f"""
            SELECT Address, count() AS n
            FROM {TABLE}
            WHERE TopicHash = '{TRANSFER_SIG}'
            GROUP BY Address
            ORDER BY n DESC
            LIMIT 10
        """)
        print(f"  {'Address':<44} {'Transfer 行数':>15}")
        print(f"  {'─' * 44} {'─' * 15}")
        for r in top_atokens:
            addr = r[0]
            if isinstance(addr, (bytes, bytearray)):
                addr = addr.decode()
            print(f"  {addr:<44} {r[1]:>15,}")

        print("\n" + "═" * 72)
        print("  探查完成。")
        print("═" * 72 + "\n")


if __name__ == "__main__":
    main()
