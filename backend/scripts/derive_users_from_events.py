"""
从 aave schema 链上事件表（borrows/deposits/repays/withdrawals）
自挖 ETH 相关活跃账户，替代 subgraph 外部数据源。

运行方式：
    uv run python scripts/derive_users_from_events.py [--output-dir ./derived_users]

输出：
    derive_users/v2_borrow.csv       —— v2 ETH 借款候选用户
    derive_users/v3_borrow.csv       —— v3 ETH 借款候选用户
    derive_users/v2_collateral.csv   —— v2 ETH 抵押候选用户
    derive_users/v3_collateral.csv   —— v3 ETH 抵押候选用户

逻辑说明：
  • 借款方向 (borrow)：在 aave_borrows 中有借 ETH 系资产记录，且 (借出总量 - 还款总量) > 0
    → 有可能仍有未还清的 ETH 头寸，RPC 调用会做精确验证
  • 抵押方向 (collateral)：在 aave_deposits 中有存入 ETH 系资产记录，
    且 (存入总量 - 提款总量) > 0
  • 协议版本区分：通过 aave_tokens.protocol_version 字段（'2' 或 '3'）确定

注意：本脚本是"宽松候选"：包含已还清但未正式关闭仓位的地址。
crawler 会调用 RPC 验证实际状态，EMPTY_POSITION 会被自动过滤。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from pathlib import Path
from typing import Any

import asyncpg
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ETH 系底层资产 symbol（与 db.py 中 _ETH_SYMBOLS 一致，加 stETH/ETHx 等）
ETH_UNDERLYING_SYMBOLS: frozenset[str] = frozenset(
    {
        "WETH",
        "wstETH",
        "cbETH",
        "rETH",
        "weETH",
        "ezETH",
        "rsETH",
        "osETH",
        "ETHx",
        "stETH",
        "cbBTC",  # cbBTC 不是 ETH 但在 _ETH_SYMBOLS 中？不加
        "tETH",  # tETH
    }
)
# 只保留 ETH 系（不含 BTC 系）
ETH_ONLY_SYMBOLS: frozenset[str] = frozenset(
    {
        "WETH",
        "wstETH",
        "cbETH",
        "rETH",
        "weETH",
        "ezETH",
        "rsETH",
        "osETH",
        "ETHx",
        "stETH",
        "tETH",
    }
)


def load_dsn() -> str:
    candidates = [
        Path.cwd() / "config.yaml",
        Path(__file__).parent.parent / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            raw = yaml.safe_load(p.read_text())
            pg = raw["postgres"]
            return (
                f"postgresql://{pg['user']}:{pg['password']}"
                f"@{pg.get('host','127.0.0.1')}:{pg.get('port',5432)}/{pg['database']}"
            )
    raise FileNotFoundError("找不到 config.yaml")


def addr_bytes_to_str(b: bytes) -> str:
    """bytea（存储了 '0x...' ASCII 字符串）→ 纯地址字符串，统一 checksum 小写"""
    text = b.decode("ascii") if isinstance(b, (bytes, bytearray)) else str(b)
    # 如果是 '0x' 开头，保留；否则加上
    text = text.strip()
    if not text.startswith("0x") and not text.startswith("0X"):
        text = "0x" + text
    return text.lower()


async def fetch_eth_token_addresses(conn: asyncpg.Connection) -> dict[str, list[str]]:
    """
    返回 {protocol_version: [addr_lower_str, ...]}
    过滤出 ETH 系底层资产（WETH, wstETH, cbETH, rETH, weETH 等）
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT
            protocol_version::text                                AS pv,
            lower(convert_from(underlying_token_address,'UTF8')) AS addr,
            underlying_token_symbol                               AS symbol
        FROM aave.aave_tokens
        WHERE chain_id = 1
          AND type::text IN ('AToken', 'VariableDebtToken')
          AND underlying_token_symbol IS NOT NULL
        ORDER BY pv, symbol
        """
    )
    result: dict[str, list[str]] = {"2": [], "3": []}
    for r in rows:
        pv, symbol, addr = r["pv"], r["symbol"], r["addr"]
        if symbol in ETH_ONLY_SYMBOLS:
            if addr not in result.setdefault(pv, []):
                result[pv].append(addr)
                logger.debug("  %s v%s → %s", symbol, pv, addr)
    return result


async def fetch_borrow_candidates(
    conn: asyncpg.Connection,
    eth_addrs: list[str],  # 已是 lower text（如 '0xc02aaa...'）
    *,
    min_net_amount: int = 0,
) -> list[dict[str, Any]]:
    """
    从 aave_borrows / aave_repays / aave_liquidations 推导净借款 > 0 的候选地址。
    按 (borrower, token) 独立计算，避免不同 token 单位混用。
    用户只要有任意一个 token 的 net_borrow > min_net_amount 即入选。
    """
    if not eth_addrs:
        return []

    n = len(eth_addrs)
    ph = ", ".join(f"${i+1}" for i in range(n))  # $1,...,$N（可在 SQL 内重复引用）
    th = f"${n + 1}"  # $N+1 = 阈值

    sql = f"""
    WITH borrow_by_token AS (
        SELECT
            lower(convert_from(borrower_address, 'UTF8')) AS addr,
            lower(convert_from(token_address,    'UTF8')) AS token,
            SUM(amount)                                    AS total_borrowed
        FROM aave.aave_borrows
        WHERE lower(convert_from(token_address, 'UTF8')) IN ({ph})
        GROUP BY 1, 2
    ),
    repay_by_token AS (
        SELECT
            lower(convert_from(borrower_address, 'UTF8')) AS addr,
            lower(convert_from(token_address,    'UTF8')) AS token,
            SUM(amount)                                    AS total_repaid
        FROM aave.aave_repays
        WHERE lower(convert_from(token_address, 'UTF8')) IN ({ph})
        GROUP BY 1, 2
    ),
    liq_by_token AS (
        SELECT
            lower(convert_from(borrower_address,      'UTF8')) AS addr,
            lower(convert_from(borrowed_token_address,'UTF8')) AS token,
            SUM(borrowed_token_amount)                          AS total_liquidated
        FROM aave.aave_liquidations
        WHERE lower(convert_from(borrowed_token_address, 'UTF8')) IN ({ph})
        GROUP BY 1, 2
    ),
    net_per_token AS (
        SELECT
            b.addr,
            b.token,
            b.total_borrowed,
            coalesce(r.total_repaid,     0) AS total_repaid,
            coalesce(l.total_liquidated, 0) AS total_liquidated,
            b.total_borrowed
                - coalesce(r.total_repaid,     0)
                - coalesce(l.total_liquidated, 0) AS net_borrow
        FROM borrow_by_token b
        LEFT JOIN repay_by_token r ON r.addr = b.addr AND r.token = b.token
        LEFT JOIN liq_by_token   l ON l.addr = b.addr AND l.token = b.token
    )
    SELECT
        addr                        AS user_address,
        COUNT(DISTINCT token)       AS active_token_count,
        SUM(total_borrowed)         AS sum_borrowed,
        SUM(total_repaid)           AS sum_repaid,
        SUM(total_liquidated)       AS sum_liquidated,
        SUM(net_borrow)             AS sum_net_borrow
    FROM net_per_token
    GROUP BY addr
    HAVING bool_or(net_borrow > {th})
    ORDER BY sum_net_borrow DESC
    """

    rows = await conn.fetch(sql, *eth_addrs, min_net_amount)
    return [dict(r) for r in rows]


async def fetch_collateral_candidates(
    conn: asyncpg.Connection,
    eth_addrs: list[str],  # 已是 lower text
    *,
    min_net_amount: int = 0,
) -> list[dict[str, Any]]:
    """
    从 aave_deposits / aave_withdrawals 推导净存款 > 0 的候选地址。
    按 (lender, token) 独立计算，用户有任意 token 净余 > min_net_amount 即入选。
    """
    if not eth_addrs:
        return []

    n = len(eth_addrs)
    ph = ", ".join(f"${i+1}" for i in range(n))
    th = f"${n + 1}"

    sql = f"""
    WITH deposit_by_token AS (
        SELECT
            lower(convert_from(lender_address, 'UTF8')) AS addr,
            lower(convert_from(token_address,  'UTF8')) AS token,
            SUM(amount)                                  AS total_deposited
        FROM aave.aave_deposits
        WHERE lower(convert_from(token_address, 'UTF8')) IN ({ph})
        GROUP BY 1, 2
    ),
    withdraw_by_token AS (
        SELECT
            lower(convert_from(lender_address, 'UTF8')) AS addr,
            lower(convert_from(token_address,  'UTF8')) AS token,
            SUM(amount)                                  AS total_withdrawn
        FROM aave.aave_withdrawals
        WHERE lower(convert_from(token_address, 'UTF8')) IN ({ph})
        GROUP BY 1, 2
    ),
    net_per_token AS (
        SELECT
            d.addr,
            d.token,
            d.total_deposited,
            coalesce(w.total_withdrawn, 0) AS total_withdrawn,
            d.total_deposited - coalesce(w.total_withdrawn, 0) AS net_deposit
        FROM deposit_by_token d
        LEFT JOIN withdraw_by_token w ON w.addr = d.addr AND w.token = d.token
    )
    SELECT
        addr                        AS user_address,
        COUNT(DISTINCT token)       AS active_token_count,
        SUM(total_deposited)        AS sum_deposited,
        SUM(total_withdrawn)        AS sum_withdrawn,
        SUM(net_deposit)            AS sum_net_deposit
    FROM net_per_token
    GROUP BY addr
    HAVING bool_or(net_deposit > {th})
    ORDER BY sum_net_deposit DESC
    """

    rows = await conn.fetch(sql, *eth_addrs, min_net_amount)
    return [dict(r) for r in rows]


async def fetch_all_borrowers_liberal(
    conn: asyncpg.Connection,
    eth_addr_list: list[str],
) -> list[dict[str, Any]]:
    """
    宽松模式：所有曾经借过 ETH 系资产的用户（无净额过滤）。
    用于解决利息导致 repay_amount > borrow_amount 的假阴性问题。
    精度低（含已还清用户），但召回率高。RPC 会做最终验证。
    """
    if not eth_addr_list:
        return []
    n = len(eth_addr_list)
    ph = ", ".join(f"${i+1}" for i in range(n))
    sql = f"""
    SELECT
        lower(convert_from(borrower_address, 'UTF8')) AS user_address,
        COUNT(DISTINCT lower(convert_from(token_address, 'UTF8'))) AS token_count,
        SUM(amount) AS total_borrowed_raw
    FROM aave.aave_borrows
    WHERE lower(convert_from(token_address, 'UTF8')) IN ({ph})
    GROUP BY 1
    ORDER BY total_borrowed_raw DESC
    """
    rows = await conn.fetch(sql, *eth_addr_list)
    return [dict(r) for r in rows]


async def fetch_history_users_by_pv(
    conn: asyncpg.Connection,
    eth_symbols: frozenset[str],
    operation: str,  # 'borrow' or 'deposit'
    protocol_version: str,  # '2' or '3'
) -> list[str]:
    """
    通过 aave_history 表（有 protocol_version 字段）精确区分 v2/v3 用户。
    返回在指定协议版本下进行过指定操作的 ETH 系资产用户地址列表。
    注意：此方法是"所有历史用户"，包含已还清，用作候选供 RPC 验证。
    """
    sym_list = list(eth_symbols)
    n = len(sym_list) + 1  # +1 for operation, +1 for pv = +2 extra params
    ph = ", ".join(f"${i+1}" for i in range(len(sym_list)))
    op_ph = f"${len(sym_list)+1}"
    pv_ph = f"${len(sym_list)+2}"

    sql = f"""
    SELECT DISTINCT
        lower(convert_from(user_address, 'UTF8')) AS user_address
    FROM aave.aave_history
    WHERE token_symbol IN ({ph})
      AND operation_type::text = {op_ph}
      AND protocol_version::text = {pv_ph}
    ORDER BY user_address
    """
    rows = await conn.fetch(sql, *sym_list, operation, protocol_version)
    return [r["user_address"] for r in rows]


async def fetch_existing_loan_users(conn: asyncpg.Connection, table: str) -> set[str]:
    """读取现有 loan.xxx 来源表中的地址（通过 subgraph 获得的）。"""
    try:
        rows = await conn.fetch(f'SELECT "walletAddress" FROM loan."{table}"')
        return {r["walletAddress"].lower() for r in rows}
    except Exception as e:
        logger.warning("读取 %s 失败: %s", table, e)
        return set()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        logger.warning("无数据，跳过写入 %s", path)
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    logger.info("写入 %s: %d 行", path, len(rows))


async def compare_with_existing(
    conn: asyncpg.Connection,
    derived_addrs: set[str],
    table: str,
    label: str,
    *,
    _existing: set[str] | None = None,
) -> None:
    """将推导出的地址与现有 subgraph 来源表做覆盖率分析。"""
    existing = (
        _existing
        if _existing is not None
        else await fetch_existing_loan_users(conn, table)
    )
    if not existing:
        logger.warning("  [%s] 来源表 %s 为空或不存在", label, table)
        return

    in_both = derived_addrs & existing
    only_derived = derived_addrs - existing
    only_existing = existing - derived_addrs
    recall = len(in_both) / len(existing) * 100 if existing else 0.0
    extra_rate = len(only_derived) / len(derived_addrs) * 100 if derived_addrs else 0.0

    logger.info(
        "  [%s] 推导:%5d | subgraph:%5d | 共同:%5d | "
        "新增:%4d | 未覆盖:%4d | 召回率:%.1f%% | 额外率:%.1f%%",
        label,
        len(derived_addrs),
        len(existing),
        len(in_both),
        len(only_derived),
        len(only_existing),
        recall,
        extra_rate,
    )
    if only_existing:
        logger.info("    ⚠  subgraph独有(前5): %s", list(only_existing)[:5])
    if only_derived:
        logger.info("    ✚  推导新增(前5): %s", list(only_derived)[:5])


async def main(output_dir: Path) -> None:
    dsn = load_dsn()
    conn = await asyncpg.connect(dsn)
    logger.info("数据库连接成功")

    # ── Step 1: 获取 ETH 系 token 地址 ──────────────────────────────────────
    logger.info("=== Step 1: 获取 ETH 系底层 token 地址（chain_id=1）===")
    eth_by_pv = await fetch_eth_token_addresses(conn)
    all_eth_addrs: list[str] = []
    for pv, addrs in sorted(eth_by_pv.items()):
        logger.info("  v%s (%d 个): %s", pv, len(addrs), addrs)
        for a in addrs:
            if a not in all_eth_addrs:
                all_eth_addrs.append(a)
    logger.info("  合并去重后共 %d 个地址", len(all_eth_addrs))

    if not all_eth_addrs:
        logger.error("未找到 ETH 系 token 地址，请检查 aave.aave_tokens 数据")
        await conn.close()
        return

    # ── Step 2A: 严格模式借款候选（per-token net_borrow > 0）────────────────
    logger.info(
        "\n=== Step 2A: 严格模式 ETH 借款候选（net > 0，利息可能导致假阴性）==="
    )
    borrow_strict = await fetch_borrow_candidates(conn, all_eth_addrs)
    logger.info("  → 严格候选借款人: %d", len(borrow_strict))

    # ── Step 2B: 宽松模式借款候选（所有历史借款人，无净额过滤）─────────────
    logger.info("\n=== Step 2B: 宽松模式 ETH 借款候选（全历史，高召回）===")
    borrow_liberal = await fetch_all_borrowers_liberal(conn, all_eth_addrs)
    logger.info("  → 宽松候选借款人: %d（含已还清）", len(borrow_liberal))

    # ── Step 2C: aave_history 精确区分 v2/v3 ─────────────────────────────────
    logger.info("\n=== Step 2C: 基于 aave_history 的 v2/v3 借款人（精确协议区分）===")
    history_borrow_v2 = await fetch_history_users_by_pv(
        conn, ETH_ONLY_SYMBOLS, "borrow", "2"
    )
    history_borrow_v3 = await fetch_history_users_by_pv(
        conn, ETH_ONLY_SYMBOLS, "borrow", "3"
    )
    logger.info("  aave_history v2 借款人: %d", len(history_borrow_v2))
    logger.info("  aave_history v3 借款人: %d", len(history_borrow_v3))

    # ── Step 3: 存款候选 ─────────────────────────────────────────────────────
    logger.info("\n=== Step 3: 存款候选 ===")
    coll_strict = await fetch_collateral_candidates(conn, all_eth_addrs)
    logger.info("  → 严格抵押候选（net > 0）: %d", len(coll_strict))

    history_deposit_v2 = await fetch_history_users_by_pv(
        conn, ETH_ONLY_SYMBOLS, "deposit", "2"
    )
    history_deposit_v3 = await fetch_history_users_by_pv(
        conn, ETH_ONLY_SYMBOLS, "deposit", "3"
    )
    logger.info("  aave_history v2 存款人: %d", len(history_deposit_v2))
    logger.info("  aave_history v3 存款人: %d", len(history_deposit_v3))

    # ── Step 4: 全面覆盖率对比 ───────────────────────────────────────────────
    logger.info("\n=== Step 4: 各方法召回率对比 ===")

    cfg = [
        # label, table, derived_set
        (
            "borrow_v2 [严格]",
            "aave_v2_eth_weth_borrow",
            {r["user_address"] for r in borrow_strict},
        ),
        (
            "borrow_v2 [宽松]",
            "aave_v2_eth_weth_borrow",
            {r["user_address"] for r in borrow_liberal},
        ),
        ("borrow_v2 [hist]", "aave_v2_eth_weth_borrow", set(history_borrow_v2)),
        (
            "borrow_v3 [严格]",
            "aave_v3_eth_weth_borrow",
            {r["user_address"] for r in borrow_strict},
        ),
        (
            "borrow_v3 [宽松]",
            "aave_v3_eth_weth_borrow",
            {r["user_address"] for r in borrow_liberal},
        ),
        ("borrow_v3 [hist]", "aave_v3_eth_weth_borrow", set(history_borrow_v3)),
        (
            "collat_v2 [严格]",
            "aave_v2_eth_weth_collateral",
            {r["user_address"] for r in coll_strict},
        ),
        ("collat_v2 [hist]", "aave_v2_eth_weth_collateral", set(history_deposit_v2)),
        (
            "collat_v3 [严格]",
            "aave_v3_eth_weth_collateral",
            {r["user_address"] for r in coll_strict},
        ),
        ("collat_v3 [hist]", "aave_v3_eth_weth_collateral", set(history_deposit_v3)),
    ]
    cached_existing: dict[str, set[str]] = {}
    for label, table, derived in cfg:
        if table not in cached_existing:
            cached_existing[table] = await fetch_existing_loan_users(conn, table)
        await compare_with_existing(
            conn, derived, table, label, _existing=cached_existing[table]
        )

    # ── Step 5: 写出 CSV ──────────────────────────────────────────────────────
    logger.info("\n=== Step 5: 写出 CSV ===")
    write_csv(output_dir / "borrow_strict.csv", borrow_strict)
    write_csv(output_dir / "borrow_liberal.csv", borrow_liberal)
    write_csv(output_dir / "collateral_strict.csv", coll_strict)

    # history-based 分 v2/v3 写出
    write_csv(
        output_dir / "history_borrow_v2.csv",
        [{"user_address": a} for a in history_borrow_v2],
    )
    write_csv(
        output_dir / "history_borrow_v3.csv",
        [{"user_address": a} for a in history_borrow_v3],
    )
    write_csv(
        output_dir / "history_deposit_v2.csv",
        [{"user_address": a} for a in history_deposit_v2],
    )
    write_csv(
        output_dir / "history_deposit_v3.csv",
        [{"user_address": a} for a in history_deposit_v3],
    )

    # ── Step 6: v3-only 统计 ─────────────────────────────────────────────────
    v3_only = [a for a in eth_by_pv.get("3", []) if a not in eth_by_pv.get("2", [])]
    if v3_only:
        logger.info("\n=== Step 6: v3 专属 ETH 代币（%d 个）===", len(v3_only))
        v3b = await fetch_borrow_candidates(conn, v3_only)
        logger.info("  仅靠 v3-only token 的严格借款候选: %d", len(v3b))

    # ── 预览 ──────────────────────────────────────────────────────────────────
    logger.info("\n=== Top-5 严格借款候选 ===")
    for r in borrow_strict[:5]:
        logger.info("  %s | net=%s", r["user_address"], str(r["sum_net_borrow"])[:20])

    logger.info("\n=== Top-5 严格存款候选 ===")
    for r in coll_strict[:5]:
        logger.info("  %s | net=%s", r["user_address"], str(r["sum_net_deposit"])[:20])

    await conn.close()
    logger.info("\n完成。CSV 已写入: %s", output_dir.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path(__file__).parent.parent / "derived_users",
        help="CSV 输出目录（默认: backend/derived_users/）",
    )
    args = parser.parse_args()
    asyncio.run(main(args.output_dir))
