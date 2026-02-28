import asyncio
import sys
from datetime import datetime, timedelta, timezone

import asyncpg

sys.path.insert(0, ".")
from aave_crawler.config import load_config

cfg = load_config()

_SQL = """
SELECT DISTINCT convert_from(addr, 'UTF8') AS address
FROM (
    SELECT user_address AS addr
      FROM aave.aave_history
     WHERE created_at > $1
       AND protocol_version = $2
    UNION ALL
    SELECT target_user_address AS addr
      FROM aave.aave_history
     WHERE created_at > $1
       AND protocol_version = $2
       AND target_user_address IS NOT NULL
       AND target_user_address <> user_address
) sub
"""

async def main():
    pool = await asyncpg.create_pool(
        host=cfg.postgres.host, port=cfg.postgres.port,
        user=cfg.postgres.user, password=cfg.postgres.password,
        database=cfg.postgres.database,
    )
    for minutes, pv in [(60, "3"), (10, "3"), (1, "3"), (60, "2"), (10, "2")]:
        watermark = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)
        try:
            rows = await pool.fetch(_SQL, watermark, pv)
            print(f"protocol_version={pv!r}, last {minutes}min -> {len(rows)} rows")
        except Exception as e:
            print(f"protocol_version={pv!r}, last {minutes}min -> ERROR: {e}")
    await pool.close()

asyncio.run(main())
