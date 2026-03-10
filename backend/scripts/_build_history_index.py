"""
在 aave.aave_history 上创建按用户地址查询的函数索引。

使用 encode(col, 'escape') 作为 IMMUTABLE 函数（对以太坊地址纯 ASCII 内容与
convert_from 等效），满足 TimescaleDB 超表及 PostgreSQL 函数索引的 IMMUTABLE 要求。
建索引期间会短暂锁表，495 万行通常 10~30 秒完成。
"""

import asyncio
import logging
import time
from pathlib import Path

import asyncpg
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    pg = cfg["postgres"]
    dsn = f"postgresql://{pg['user']}:{pg['password']}@{pg['host']}:{pg['port']}/{pg['database']}"

    # CONCURRENTLY 必须在 autocommit 连接上执行（不在事务内）
    conn = await asyncpg.connect(dsn)

    # TimescaleDB 超表不支持 CONCURRENTLY，使用普通 CREATE INDEX。
    # convert_from() 非 IMMUTABLE，改用 encode(col, 'escape')：
    # 对纯 ASCII 内容（以太坊地址格式 0x + hex），输出与 convert_from 完全相同，
    # 且 encode() 是 IMMUTABLE，满足函数索引要求。
    indexes = [
        (
            "idx_aave_history_user_ts",
            """
            CREATE INDEX IF NOT EXISTS idx_aave_history_user_ts
                ON aave.aave_history
                (lower(encode(user_address, 'escape')), created_at DESC)
            """,
        ),
        (
            "idx_aave_history_target_ts",
            """
            CREATE INDEX IF NOT EXISTS idx_aave_history_target_ts
                ON aave.aave_history
                (lower(encode(target_user_address, 'escape')), created_at DESC)
            WHERE target_user_address IS NOT NULL
            """,
        ),
    ]

    for name, ddl in indexes:
        # 先检查是否已存在
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_indexes WHERE schemaname='aave' AND indexname=$1", name
        )
        if exists:
            logger.info("索引已存在，跳过：%s", name)
            continue

        logger.info("开始建索引：%s ...", name)
        t0 = time.monotonic()
        await conn.execute(ddl)
        elapsed = time.monotonic() - t0
        logger.info("索引建立完成：%s（耗时 %.1fs）", name, elapsed)

    # 验证结果
    rows = await conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='aave' AND tablename='aave_history'"
    )
    logger.info("当前 aave.aave_history 全部索引：")
    for r in rows:
        logger.info("  %s", r["indexname"])

    await conn.close()


asyncio.run(main())
