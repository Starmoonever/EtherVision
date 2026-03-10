"""临时脚本：检查 aave.aave_history 表结构"""

import asyncio
from pathlib import Path

import asyncpg
import yaml


async def main():
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    pg = cfg["postgres"]
    dsn = f"postgresql://{pg['user']}:{pg['password']}@{pg['host']}:{pg['port']}/{pg['database']}"

    conn = await asyncpg.connect(dsn)

    cols = await conn.fetch("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='aave' AND table_name='aave_history'
        ORDER BY ordinal_position
    """)
    print("=== aave.aave_history 字段 ===")
    for c in cols:
        print(f"  {c['column_name']:30s} {c['data_type']}")

    row = await conn.fetchrow("SELECT * FROM aave.aave_history LIMIT 1")
    print("\n=== 样本 ===")
    if row:
        for k, v in dict(row).items():
            print(f"  {k:30s} = {str(v)[:60]}")

    idxs = await conn.fetch("""
        SELECT indexname, indexdef FROM pg_indexes
        WHERE schemaname='aave' AND tablename='aave_history'
    """)
    print("\n=== 索引 ===")
    for i in idxs:
        print(f"  {i['indexname']}")
        print(f"    {i['indexdef']}")

    cnt = await conn.fetchval("SELECT COUNT(*) FROM aave.aave_history")
    print(f"\n总行数: {cnt:,}")

    await conn.close()


asyncio.run(main())
