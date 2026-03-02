"""检查 aave 事件表的时间边界（ULID 解码为时间戳）"""
import asyncio
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import yaml


async def main():
    raw = yaml.safe_load(Path(__file__).parent.parent.joinpath("config.yaml").read_text())
    pg = raw["postgres"]
    dsn = f"postgresql://{pg['user']}:{pg['password']}@{pg.get('host','127.0.0.1')}:{pg.get('port',5432)}/{pg['database']}"
    conn = await asyncpg.connect(dsn)

    def ulid_to_ts(u) -> datetime | None:
        """UUID 中 ULID 的前 48 bits 是 Unix 毫秒时间戳"""
        if u is None: return None
        b = u.bytes  # 16 bytes
        ms = int.from_bytes(b[:6], "big")
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    for table in ["aave_borrows", "aave_deposits", "aave_repays", "aave_withdrawals"]:
        rows = await conn.fetch(f"""
            SELECT ulid FROM aave.{table}
            ORDER BY ulid::text ASC LIMIT 1
        """)
        first_ulid = rows[0]["ulid"] if rows else None

        rows = await conn.fetch(f"""
            SELECT ulid FROM aave.{table}
            ORDER BY ulid::text DESC LIMIT 1
        """)
        last_ulid = rows[0]["ulid"] if rows else None

        cnt = await conn.fetchval(f"SELECT COUNT(*) FROM aave.{table}")
        first_ts = ulid_to_ts(first_ulid)
        last_ts  = ulid_to_ts(last_ulid)
        print(f"{table:25s}  {cnt:>8,} rows  | "
              f"{str(first_ts)[:10] if first_ts else '?'} ~ {str(last_ts)[:10] if last_ts else '?'}")

    # aave_history 结构
    cols = await conn.fetch("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='aave' AND table_name='aave_history'
        ORDER BY ordinal_position
    """)
    print("\naave_history 列:")
    for c in cols:
        print(f"  {c['column_name']:30s} {c['data_type']}")

    rows = await conn.fetch("SELECT * FROM aave.aave_history LIMIT 2")
    print("\naave_history 样本:")
    for r in rows:
        print({k: str(v)[:60] for k, v in dict(r).items()})

    await conn.close()

asyncio.run(main())
