"""验证 aave_position_snapshots 表结构"""

import asyncio
from pathlib import Path

import asyncpg
import yaml


async def main():
    with open(Path(__file__).parent.parent / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    pg = cfg["postgres"]
    dsn = f"postgresql://{pg['user']}:{pg['password']}@{pg['host']}:{pg['port']}/{pg['database']}"
    conn = await asyncpg.connect(dsn)

    cols = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='loan' AND table_name='aave_position_snapshots' "
        "ORDER BY ordinal_position"
    )
    print("loan.aave_position_snapshots 字段:")
    for c in cols:
        print(f"  {c['column_name']:25s} {c['data_type']}")

    idxs = await conn.fetch(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname='loan' AND tablename='aave_position_snapshots'"
    )
    print("索引:", [r["indexname"] for r in idxs])

    await conn.close()


asyncio.run(main())
