"""
探索 aave schema 关键细节：
- aave_tokens 内容（token 类型、协议版本、WETH 地址）
- borrow/deposit 事件样本（解码地址）
- 与 loan.aave_v* 来源表的数量对比
"""
import asyncio
from pathlib import Path

import asyncpg
import yaml


async def main():
    raw = yaml.safe_load(Path(__file__).parent.parent.joinpath("config.yaml").read_text())
    pg = raw["postgres"]
    dsn = (
        f"postgresql://{pg['user']}:{pg['password']}"
        f"@{pg.get('host','127.0.0.1')}:{pg.get('port',5432)}/{pg['database']}"
    )
    conn = await asyncpg.connect(dsn)

    # ── aave_tokens 全貌 ──────────────────────────────────────────────────────
    print("=== aave_tokens (all) ===")
    rows = await conn.fetch(
        "SELECT chain_id, encode(address,'hex') AS addr, symbol, type, decimals, "
        "       encode(underlying_token_address,'hex') AS underlying, underlying_token_symbol, protocol_version "
        "FROM aave.aave_tokens ORDER BY protocol_version, symbol"
    )
    for r in rows:
        print(dict(r))

    # ── WETH 相关 token ───────────────────────────────────────────────────────
    print("\n=== ETH-related tokens ===")
    rows = await conn.fetch(
        "SELECT chain_id, encode(address,'hex') AS addr, symbol, type, decimals, "
        "       encode(underlying_token_address,'hex') AS underlying, underlying_token_symbol, protocol_version "
        "FROM aave.aave_tokens WHERE upper(symbol) LIKE '%ETH%' OR upper(underlying_token_symbol) LIKE '%ETH%'"
    )
    for r in rows:
        print(dict(r))

    # ── borrow 样本（解码） ───────────────────────────────────────────────────
    print("\n=== aave_borrows 5 rows decoded ===")
    rows = await conn.fetch("""
        SELECT
            encode(b.tx_hash, 'hex')          AS tx_hash,
            encode(b.token_address, 'hex')    AS token_addr,
            t.symbol,
            t.protocol_version,
            b.amount / (10::numeric ^ coalesce(t.decimals, 18)) AS amount,
            encode(b.borrower_address, 'hex') AS borrower,
            b.rate_mode
        FROM aave.aave_borrows b
        LEFT JOIN aave.aave_tokens t
               ON t.address = b.token_address AND t.type = 'Underlying'
        LIMIT 5
    """)
    for r in rows:
        print(dict(r))

    # ── deposit 样本（解码） ──────────────────────────────────────────────────
    print("\n=== aave_deposits 5 rows decoded ===")
    rows = await conn.fetch("""
        SELECT
            encode(d.token_address, 'hex')  AS token_addr,
            t.symbol,
            t.protocol_version,
            d.amount / (10::numeric ^ coalesce(t.decimals, 18)) AS amount,
            encode(d.lender_address, 'hex') AS lender,
            encode(d.payer_address, 'hex')  AS payer
        FROM aave.aave_deposits d
        LEFT JOIN aave.aave_tokens t
               ON t.address = d.token_address AND t.type = 'Underlying'
        LIMIT 5
    """)
    for r in rows:
        print(dict(r))

    # ── loan schema 来源表行数 ────────────────────────────────────────────────
    print("\n=== loan source tables (subgraph-derived) ===")
    for tname in [
        "aave_v3_eth_weth_collateral",
        "aave_v3_eth_weth_borrow",
        "aave_v2_eth_weth_collateral",
        "aave_v2_eth_weth_borrow",
    ]:
        try:
            cnt = await conn.fetchval(f'SELECT COUNT(*) FROM loan."{tname}"')
            cols = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema='loan' AND table_name='{tname}' ORDER BY ordinal_position"
            )
            print(f"  {tname}: {cnt:,} rows | cols: {[c['column_name'] for c in cols]}")
            sample = await conn.fetch(f'SELECT * FROM loan."{tname}" LIMIT 2')
            for r in sample:
                print(f"    {dict(r)}")
        except Exception as e:
            print(f"  {tname}: ERROR {e}")

    # ── 现有 loan positions 表行数 ────────────────────────────────────────────
    print("\n=== loan positions tables ===")
    for tname in [
        "aave_v3_eth_positions_collateral",
        "aave_v3_eth_positions_borrow",
        "aave_v2_eth_positions_collateral",
        "aave_v2_eth_positions_borrow",
    ]:
        try:
            cnt = await conn.fetchval(f'SELECT COUNT(*) FROM loan."{tname}"')
            print(f"  {tname}: {cnt:,} rows")
        except Exception as e:
            print(f"  {tname}: ERROR {e}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
