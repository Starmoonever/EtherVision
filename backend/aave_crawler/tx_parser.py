"""tx_parser.py — 从 aave_history 生成人类可读的操作摘要 (brief)。

格式："{操作类型} {数量} {token符号} (价值 {value} usd)"

  - 操作类型（6种中文）：deposit→存入, withdraw→取出, borrow→借出,
                         repay→偿还, liquidate→清算, flashloan→闪电贷
  - 数量：amount / 10^decimals，最多 6 位有效小数（尾零去掉）
  - 价值：仅当 token_symbol 在 Aave reserve 中（即能从市场快照表找到 price_usd）时显示

用法::

    from aave_crawler.tx_parser import parse_tx_briefs, parse_briefs_from_metas

    # 批量按 tx_hash 从 aave_history 生成 brief（需要 asyncpg Pool）
    briefs = await parse_tx_briefs(pool, ["0xabc...", "0xdef..."], protocol="v3")
    # -> ["存入 1.5 WETH (价值 3000.00 usd)", "借出 500 USDC (价值 500.00 usd)"]
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import asyncpg

logger = logging.getLogger(__name__)

# ── 操作类型 → 中文标签（6 种）────────────────────────────────────────────────
_OP_LABELS: dict[str, str] = {
    "deposit": "存入",
    "withdraw": "取出",
    "borrow": "借出",
    "repay": "偿还",
    "liquidate": "清算",
    "flashloan": "闪电贷",
}

# protocol → 版本标签（用于 brief 前缀 "在 Aave V{n}"）
_VERSION_LABEL: dict[str, str] = {
    "v2": "V2",
    "v2_borrow": "V2",
    "v3": "V3",
    "v3_borrow": "V3",
}

# uint256.max 哨兵（Aave 用于"全额"操作）
_SENTINEL = Decimal(10) ** 75

# ── SQL ───────────────────────────────────────────────────────────────────────

# 按 tx_hash 批量查询操作数据；DISTINCT ON 确保每个 tx_hash 只取一条
_SQL_HISTORY_BY_TXHASH = """
SELECT DISTINCT ON (lower(encode(tx_hash, 'escape')))
    lower(encode(tx_hash, 'escape'))    AS tx_hash,
    operation_type::text                AS operation_type,
    token_symbol,
    convert_from(token_address, 'UTF8') AS token_address,
    amount,
    decimals,
    block_number
FROM aave.aave_history
WHERE lower(encode(tx_hash, 'escape')) = ANY($1::text[])
ORDER BY lower(encode(tx_hash, 'escape')), block_number DESC
"""

# 从市场快照表查最近 block 的 token 价格（"在 reserve 中"的判断依据）
_SQL_PRICE = """
SELECT price_usd
FROM loan.{table}
WHERE lower(token_address) = lower($1)
  AND block_number <= $2
ORDER BY block_number DESC
LIMIT 1
"""

# 协议 → 市场快照表名
_SNAPSHOTS_TABLE: dict[str, str] = {
    "v3": "aave_v3_eth_market_snapshots",
    "v2": "aave_v2_eth_market_snapshots",
}

# ── 格式化工具 ────────────────────────────────────────────────────────────────


def _fmt_amount(amount_int: int | str, decimals: int) -> str:
    """原始整数 → 可读小数，最多 6 位，去尾零。uint256.max 返回 '全部'。"""
    try:
        v = Decimal(str(amount_int))
        if v >= _SENTINEL:
            return "全部"
        return f"{v / Decimal(10 ** decimals):.6f}".rstrip("0").rstrip(".")
    except (InvalidOperation, TypeError):
        return str(amount_int)


def generate_brief(
    op: str,
    amount_int: int | str,
    decimals: int,
    symbol: str,
    price_usd: Decimal | None = None,
    protocol: str = "",
) -> str:
    """生成单条操作的人类可读摘要。

    格式："在 Aave {version} {操作类型} {数量} {symbol} (价值 {value} usd)"
    price_usd 为 None 时省略价值部分；protocol 为空时省略版本前缀。
    """
    label = _OP_LABELS.get((op or "").lower(), op or "")
    amt_str = _fmt_amount(amount_int, decimals)
    ver = _VERSION_LABEL.get((protocol or "").lower(), "")
    prefix = f"在 Aave {ver} " if ver else ""
    if not symbol:
        return f"{prefix}{label} {amt_str}"
    if price_usd and price_usd > 0:
        try:
            v = Decimal(str(amount_int))
            if v < _SENTINEL:
                usd = v / Decimal(10**decimals) * price_usd
                return f"{prefix}{label} {amt_str} {symbol} (价值 {usd:.2f} usd)"
        except Exception:
            pass
    return f"{prefix}{label} {amt_str} {symbol}"


# ── 价格查询（从市场快照表）──────────────────────────────────────────────────


async def _lookup_price(
    pool: asyncpg.Pool,
    token_address: str,
    block_number: int,
    protocol: str,
) -> Decimal | None:
    """查询市场快照表中最近 block 的 price_usd。不在 reserve 中则返回 None。"""
    table = _SNAPSHOTS_TABLE.get(protocol, _SNAPSHOTS_TABLE["v3"])
    sql = _SQL_PRICE.format(table=table)
    try:
        row = await pool.fetchrow(sql, token_address.lower(), block_number)
        if row and row["price_usd"]:
            return Decimal(str(row["price_usd"]))
    except Exception as exc:
        logger.debug("brief: price lookup failed (%s): %s", token_address, exc)
    return None


# ── 公开接口 ──────────────────────────────────────────────────────────────────


async def parse_tx_briefs(
    pool: asyncpg.Pool,
    tx_hashes: list[str],
    protocol: str = "v3",
) -> list[str]:
    """批量生成 brief，从 aave_history 读取操作数据，从市场快照表读取价格。

    :param pool:      asyncpg 连接池
    :param tx_hashes: tx hash 列表
    :param protocol:  'v2' | 'v3'
    :returns:         与 tx_hashes 等长的 brief 列表，无数据的项返回空字符串
    """
    if not tx_hashes:
        return []

    lc = [h.lower() for h in tx_hashes]
    try:
        rows = await pool.fetch(_SQL_HISTORY_BY_TXHASH, lc)
    except Exception as exc:
        logger.warning("parse_tx_briefs: DB query failed: %s", exc)
        return [""] * len(tx_hashes)

    row_map: dict[str, asyncpg.Record] = {r["tx_hash"]: r for r in rows}

    results: list[str] = []
    for h in lc:
        row = row_map.get(h)
        if row is None:
            results.append("")
            continue
        token_addr = (row["token_address"] or "").lower()
        price = await _lookup_price(pool, token_addr, row["block_number"], protocol)
        results.append(
            generate_brief(
                row["operation_type"],
                row["amount"],
                row["decimals"],
                row["token_symbol"] or "",
                price,
                protocol,
            )
        )
    return results


async def parse_briefs_from_metas(
    pool: asyncpg.Pool,
    metas: list[dict],
) -> list[str]:
    """从 meta 列表批量生成 brief，优先使用 meta["prices"] 中的实时价格。

    meta 格式：
      - ``tx_hash``:   str
      - ``protocol``:  str ('v2' | 'v3')
      - ``prices``:    dict[str, Decimal]  token_address_lower → price_usd  （可选）

    prices 来自 RPC 同 block 采集，精确度高于市场快照表；不存在时回退到快照表。

    :returns: 与 metas 等长的 brief 列表，失败项返回空字符串
    """
    if not metas:
        return []

    lc_hashes = [m["tx_hash"].lower() for m in metas]
    try:
        rows = await pool.fetch(_SQL_HISTORY_BY_TXHASH, lc_hashes)
    except Exception as exc:
        logger.warning("parse_briefs_from_metas: DB query failed: %s", exc)
        return [""] * len(metas)

    row_map: dict[str, asyncpg.Record] = {r["tx_hash"]: r for r in rows}

    results: list[str] = []
    for meta in metas:
        h = meta["tx_hash"].lower()
        row = row_map.get(h)
        if row is None:
            results.append("")
            continue

        token_addr = (row["token_address"] or "").lower()
        prices_dict: dict[str, Decimal] = meta.get("prices") or {}
        price: Decimal | None = prices_dict.get(token_addr)

        if price is None:
            # 回退：从市场快照表查（token 在 reserve 中才有记录）
            price = await _lookup_price(
                pool,
                token_addr,
                row["block_number"],
                meta.get("protocol", "v3"),
            )

        results.append(
            generate_brief(
                row["operation_type"],
                row["amount"],
                row["decimals"],
                row["token_symbol"] or "",
                price,
                meta.get("protocol", "v3"),
            )
        )
    return results
