"""创建 loan.aave_position_snapshots 表及索引"""

import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from aave_crawler.config import load_config
from aave_crawler.db import create_pool, ensure_snapshot_cache_table


async def main():
    cfg = load_config(Path(__file__).parent.parent / "config.yaml")
    pool = await create_pool(cfg.postgres)
    await ensure_snapshot_cache_table(pool)
    await pool.close()
    print("Done.")


asyncio.run(main())
