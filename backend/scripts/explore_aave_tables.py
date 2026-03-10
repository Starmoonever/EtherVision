"""
探索 aave schema 下各事件表结构，为自挖用户账户信息做前期分析。
"""

import asyncio
from pathlib import Path

import asyncpg
import yaml


async def main():
    raw = yaml.safe_load(
        Path(__file__).parent.parent.joinpath("config.yaml").read_text()
    )
    pg = raw["postgres"]
    dsn = f"postgresql://{pg['user']}:{pg['password']}@{pg.get('host', '127.0.0.1')}:{pg.get('port', 5432)}/{pg['database']}"
    conn = await asyncpg.connect(dsn)

    # ── 各事件表结构 + 行数 ─────────────────────────────────────────────────
    for tname in [
        "aave_borrows",
        "aave_deposits",
        "aave_repays",
        "aave_withdrawals",
        "aave_liquidations",
        "aave_tokens",
        "aave_reserve_data",
    ]:
        cols = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='aave' AND table_name=$1 ORDER BY ordinal_position",
            tname,
        )
        cnt = await conn.fetchval(f"SELECT COUNT(*) FROM aave.{tname}")
        print(f"\n=== aave.{tname} ({cnt:,} rows) ===")
        for c in cols:
            print(f"  {c['column_name']:35s} {c['data_type']}")

    # ── aave_tokens：token 元数据（symbol、decimals 等）──────────────────────
    print("\n=== aave_tokens sample ===")
    rows = await conn.fetch("SELECT * FROM aave.aave_tokens LIMIT 30")
    for r in rows:
        print(dict(r))

    # ── aave_borrows：样本 ────────────────────────────────────────────────────
    print("\n=== aave_borrows sample (5 rows, decoded) ===")
    rows = await conn.fetch(
        """
        SELECT
            encode(b.tx_hash, 'hex')          AS tx_hash,
            encode(b.token_address, 'hex')    AS token_address,
            t.symbol,
            t.decimals,
            b.amount / (10::numeric ^ t.decimals) AS amount_human,
            encode(b.borrower_address, 'hex') AS borrower,
            b.rate_mode,
            b.ulid
        FROM aave.aave_borrows b
        LEFT JOIN aave.aave_tokens t ON t.token_address = b.token_address
        LIMIT 5
    """
    )
    for r in rows:
        print(dict(r))

    # ── aave_deposits 样本 ───────────────────────────────────────────────────
    print("\n=== aave_deposits sample (3 rows) ===")
    rows = await conn.fetch(
        """
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema='aave' AND table_name='aave_deposits'
        ORDER BY ordinal_position
    """
    )
    for c in rows:
        print(f"  {c['column_name']:35s} {c['data_type']}")
    rows = await conn.fetch("SELECT * FROM aave.aave_deposits LIMIT 3")
    for r in rows:
        print(dict(r))

    # ── aave_repays 样本 ─────────────────────────────────────────────────────
    print("\n=== aave_repays sample (3 rows) ===")
    rows = await conn.fetch("SELECT * FROM aave.aave_repays LIMIT 3")
    for r in rows:
        print(dict(r))

    # ── 找出 WETH token_address ──────────────────────────────────────────────
    print("\n=== WETH token info ===")
    rows = await conn.fetch(
        "SELECT * FROM aave.aave_tokens WHERE upper(symbol) LIKE '%ETH%'"
    )
    for r in rows:
        print(dict(r))

    # ── 统计：按 token 分组，借款活跃用户数 ──────────────────────────────────
    print("\n=== borrow active users by token (top 10) ===")
    rows = await conn.fetch(
        """
        SELECT
            coalesce(t.symbol, encode(b.token_address,'hex')) AS symbol,
            COUNT(DISTINCT b.borrower_address)                AS unique_borrowers,
            SUM(b.amount / (10::numeric ^ coalesce(t.decimals, 18))) AS total_borrowed
        FROM aave.aave_borrows b
        LEFT JOIN aave.aave_tokens t ON t.token_address = b.token_address
        GROUP BY 1
        ORDER BY unique_borrowers DESC
        LIMIT 10
    """
    )
    for r in rows:
        print(dict(r))

    # ── ulid 是否含时间信息（ULID = 时间+随机，前48bit是毫秒时间戳）─────────
    print("\n=== ULID-based time range of aave_borrows ===")
    rows = await conn.fetch(
        """
        SELECT
            min(ulid) AS min_ulid,
            max(ulid) AS max_ulid
        FROM aave.aave_borrows
    """
    )
    for r in rows:
        print(dict(r))

    # ── loan schema 的来源表看一下列 ─────────────────────────────────────────
    print("\n=== loan schema tables ===")
    rows = await conn.fetch(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='loan' ORDER BY table_name
    """
    )
    for r in rows:
        tname = r["table_name"]
        cnt = await conn.fetchval(f'SELECT COUNT(*) FROM loan."{tname}"')
        print(f"  {tname:55s} {cnt:>10,} rows")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
