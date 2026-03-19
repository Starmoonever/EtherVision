"""
sync_atoken_transfers.py
────────────────────────────────────────────────────────────────────────────────
从 ClickHouse eth_defi.rrmt_logs 中拉取 Aave aToken ERC-20 Transfer 事件，
写入 PostgreSQL loan.aave_atoken_transfers 表（增量同步）。

首次运行前，先建表：
    uv run python scripts/sync_atoken_transfers.py --init-db

增量同步（从上次水位线继续）：
    uv run python scripts/sync_atoken_transfers.py

全量重建（清空后重新同步）：
    uv run python scripts/sync_atoken_transfers.py --full

指定区块范围（覆盖水位线）：
    uv run python scripts/sync_atoken_transfers.py --from-block 16308190 --to-block 24682425

用法帮助：
    uv run python scripts/sync_atoken_transfers.py --help

────────────────────────────────────────────────────────────────────────────────
rrmt_logs 字段说明：
  TopicHash   FixedString(66)  = topic[0]（带 0x 小写）
  Address     FixedString(42)  = 合约地址（带 0x 小写）
  Topics      String           = topic[1..N] 逗号分隔（不含 topic0）
  Data        String           = ABI-encoded event data
  BlockNumber UInt64
  Hash        FixedString(66)  = tx hash
  CreatedAt   DateTime
  Serial      UInt64           = 区块内 log index（每块从 0 重新计数，非全局唯一）

ERC-20 Transfer(address indexed from, address indexed to, uint256 value):
  topic[1] = from  → Topics split[0]（32 字节 padded，后 40 字符 = 地址）
  topic[2] = to    → Topics split[1]（同上）
  data     = value（uint256，带或不带 0x 前缀 hex 字符串）

唯一键：(block_number, log_index) 即 (BlockNumber, Serial)
水位线：已同步到的最大 block_number
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import asyncpg
from web3 import Web3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.clickhouse import ClickHouseClient  # noqa: E402
from aave_crawler.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

CH_TABLE = "eth_defi.rrmt_logs"

# ClickHouse 每批覆盖的区块跨度
CH_BATCH_BLOCKS = 100_000

# 单次 CH query 最大返回行（防爆内存）
CH_MAX_ROWS_PER_FETCH = 500_000

# PostgreSQL 每批 COPY 行数
PG_COPY_BATCH = 50_000

# ── DataProvider 合约地址（Ethereum Mainnet）─────────────────────────────────

_DP_V3 = Web3.to_checksum_address("0x7B4EB56E7CD4b454BA8ff71E4518426369a138a3")
_DP_V2 = Web3.to_checksum_address("0x057835Ad21a177dbdd3090bB1CAE03EaCF78Fc6d")

# getReserveTokensAddresses(address asset) → (aToken, stableDebt, variableDebt)
_GET_RESERVE_TOKENS_ABI = [
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveTokensAddresses",
        "outputs": [
            {"name": "aTokenAddress", "type": "address"},
            {"name": "stableDebtTokenAddress", "type": "address"},
            {"name": "variableDebtTokenAddress", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# ── DDL ───────────────────────────────────────────────────────────────────────

DDL_TRANSFERS = """
CREATE TABLE IF NOT EXISTS loan.aave_atoken_transfers (
    block_number    BIGINT          NOT NULL,
    log_index       INT             NOT NULL,   -- rrmt_logs.Serial（区块内 log index）
    block_ts        TIMESTAMPTZ     NOT NULL,   -- rrmt_logs.CreatedAt（近似区块时间）
    tx_hash         CHAR(66)        NOT NULL,   -- 0x + 64 hex
    atoken_address  CHAR(42)        NOT NULL,   -- 0x + 40 hex（小写）
    from_address    CHAR(42)        NOT NULL,
    to_address      CHAR(42)        NOT NULL,
    amount_raw      NUMERIC(78, 0)  NOT NULL,   -- uint256 原始值
    synced_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (block_number, log_index)
);
"""

DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_aat_atoken_block
    ON loan.aave_atoken_transfers (atoken_address, block_number);

CREATE INDEX IF NOT EXISTS idx_aat_from_block
    ON loan.aave_atoken_transfers (from_address, block_number);

CREATE INDEX IF NOT EXISTS idx_aat_to_block
    ON loan.aave_atoken_transfers (to_address, block_number);
"""

DDL_SYNC_META = """
CREATE TABLE IF NOT EXISTS loan.aave_atoken_transfer_sync (
    id              SERIAL          PRIMARY KEY,
    last_block      BIGINT          NOT NULL DEFAULT 0,
    synced_rows     BIGINT          NOT NULL DEFAULT 0,
    finished_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
"""


# ── aToken 地址加载 ────────────────────────────────────────────────────────────


async def _load_atoken_addresses(pool: asyncpg.Pool, rpc_url: str) -> list[str]:
    """
    通过两步查出所有 aToken 合约地址：

    1. 从 market_snapshots 取底层资产地址（token_address），区分 V3/V2
    2. 对每个底层资产调用 DataProvider.getReserveTokensAddresses(asset)，
       取返回值第一项（aTokenAddress）
    """
    rows_v3 = await pool.fetch(
        "SELECT DISTINCT lower(token_address) AS addr "
        "FROM loan.aave_v3_market_snapshots WHERE token_address IS NOT NULL"
    )
    rows_v2 = await pool.fetch(
        "SELECT DISTINCT lower(token_address) AS addr "
        "FROM loan.aave_v2_market_snapshots WHERE token_address IS NOT NULL"
    )

    underlying_v3 = [r["addr"] for r in rows_v3]
    underlying_v2 = [r["addr"] for r in rows_v2]
    logger.info(
        "底层资产：V3=%d 个，V2=%d 个，开始查 aToken 地址",
        len(underlying_v3),
        len(underlying_v2),
    )

    if not underlying_v3 and not underlying_v2:
        logger.warning("market_snapshots 无数据，返回空列表")
        return []

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    atoken_addresses: list[str] = []

    for dp_addr, underlyings, label in [
        (_DP_V3, underlying_v3, "V3"),
        (_DP_V2, underlying_v2, "V2"),
    ]:
        if not underlyings:
            continue
        contract = w3.eth.contract(address=dp_addr, abi=_GET_RESERVE_TOKENS_ABI)
        for asset in underlyings:
            try:
                result = contract.functions.getReserveTokensAddresses(
                    Web3.to_checksum_address(asset)
                ).call()
                atoken = result[0].lower()
                atoken_addresses.append(atoken)
                logger.debug("%s %s → aToken %s", label, asset, atoken)
            except Exception as exc:
                logger.warning(
                    "%s %s getReserveTokensAddresses 失败: %s", label, asset, exc
                )

    logger.info("共获得 %d 个 aToken 地址", len(atoken_addresses))
    return atoken_addresses


# ── ClickHouse 查询 ────────────────────────────────────────────────────────────


def _decode_address(padded: str) -> str:
    """32 字节 padded topic → 42 字符地址（0x + 40 hex，小写）。"""
    s = padded.strip()
    if s.startswith(("0x", "0X")):
        s = s[2:]
    return "0x" + s[-40:].lower()


def _decode_amount(data: str) -> int:
    """ABI-encoded uint256 data → Python int。"""
    s = data.strip()
    if not s or s in ("0x", "0X"):
        return 0
    if s.startswith(("0x", "0X")):
        s = s[2:]
    return int(s, 16)


def _fetch_ch_batch(
    ch: ClickHouseClient,
    atoken_in: str,
    block_from: int,
    block_to: int,  # 含边界
) -> list[tuple]:
    """
    拉取 [block_from, block_to] 区块范围内目标 aToken 的 Transfer 事件。

    返回列：Serial(log_index), BlockNumber, Hash, Address, Topics, Data, CreatedAt
    """
    sql = f"""
        SELECT
            Serial,
            BlockNumber,
            Hash,
            Address,
            Topics,
            Data,
            CreatedAt
        FROM {CH_TABLE}
        WHERE TopicHash = '{TRANSFER_SIG}'
          AND Address IN ({atoken_in})
          AND BlockNumber >= {block_from}
          AND BlockNumber <= {block_to}
        ORDER BY BlockNumber, Serial
        LIMIT {CH_MAX_ROWS_PER_FETCH}
    """
    return ch.query(sql)


# ── 水位线管理 ─────────────────────────────────────────────────────────────────


async def _get_last_block(pool: asyncpg.Pool) -> int:
    """返回已安全写入的最大 block_number，同时看进度表和 transfers 表，取较大值。"""
    row = await pool.fetchrow("""
        SELECT GREATEST(
            COALESCE((SELECT MAX(last_block)    FROM loan.aave_atoken_transfer_sync), 0),
            COALESCE((SELECT MAX(block_number)  FROM loan.aave_atoken_transfers),     0)
        ) AS b
    """)
    return int(row["b"])


async def _save_progress(
    pool: asyncpg.Pool,
    last_block: int,
    synced_rows: int,
) -> None:
    await pool.execute(
        "INSERT INTO loan.aave_atoken_transfer_sync (last_block, synced_rows) VALUES ($1, $2)",
        last_block,
        synced_rows,
    )


# ── 主同步流程 ─────────────────────────────────────────────────────────────────


async def _sync(
    pool: asyncpg.Pool,
    ch: ClickHouseClient,
    atoken_addresses: list[str],
    start_block: int,
    end_block: int,
) -> int:
    """
    同步 [start_block, end_block] 区块范围内的 Transfer 事件。
    按 CH_BATCH_BLOCKS 分片逐批处理，每批写完更新进度。

    返回本次写入总行数。
    """
    atoken_in = ", ".join(f"'{a}'" for a in atoken_addresses)
    total_written = 0
    cursor = start_block

    while cursor <= end_block:
        batch_end = min(cursor + CH_BATCH_BLOCKS - 1, end_block)
        logger.info(
            "  CH fetch block [%d, %d]  (目标范围 [%d, %d])",
            cursor,
            batch_end,
            start_block,
            end_block,
        )

        rows = _fetch_ch_batch(ch, atoken_in, cursor, batch_end)
        if not rows:
            cursor = batch_end + 1
            continue

        # 解析行
        records: list[tuple] = []
        for r in rows:
            log_index, block_num, tx_hash, address, topics_str, data, created_at = r

            if isinstance(tx_hash, (bytes, bytearray)):
                tx_hash = tx_hash.decode()
            if isinstance(address, (bytes, bytearray)):
                address = address.decode()

            parts = topics_str.split(",") if isinstance(topics_str, str) else []
            if len(parts) < 2:
                continue

            from_addr = _decode_address(parts[0])
            to_addr = _decode_address(parts[1])
            amount = _decode_amount(data if isinstance(data, str) else "")

            records.append(
                (
                    int(block_num),  # block_number
                    int(log_index),  # log_index  (= Serial，区块内 log index)
                    created_at,  # block_ts
                    tx_hash.lower(),  # tx_hash
                    address.lower(),  # atoken_address
                    from_addr,  # from_address
                    to_addr,  # to_address
                    amount,  # amount_raw
                )
            )

        if not records:
            cursor = batch_end + 1
            continue

        # 分批写入（临时表 → ON CONFLICT DO NOTHING）
        batch_written = 0
        for i in range(0, len(records), PG_COPY_BATCH):
            chunk = records[i : i + PG_COPY_BATCH]
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        CREATE TEMP TABLE _aat_tmp (
                            block_number    BIGINT,
                            log_index       INT,
                            block_ts        TIMESTAMPTZ,
                            tx_hash         TEXT,
                            atoken_address  TEXT,
                            from_address    TEXT,
                            to_address      TEXT,
                            amount_raw      NUMERIC(78, 0)
                        ) ON COMMIT DROP
                    """)
                    await conn.copy_records_to_table(
                        "_aat_tmp",
                        records=chunk,
                        columns=[
                            "block_number",
                            "log_index",
                            "block_ts",
                            "tx_hash",
                            "atoken_address",
                            "from_address",
                            "to_address",
                            "amount_raw",
                        ],
                    )
                    n_inserted = await conn.fetchval("""
                        WITH ins AS (
                            INSERT INTO loan.aave_atoken_transfers
                                (block_number, log_index, block_ts, tx_hash,
                                 atoken_address, from_address, to_address, amount_raw)
                            SELECT block_number, log_index, block_ts, tx_hash,
                                   atoken_address, from_address, to_address, amount_raw
                            FROM _aat_tmp
                            ON CONFLICT (block_number, log_index) DO NOTHING
                            RETURNING 1
                        )
                        SELECT COUNT(*) FROM ins
                    """)
                    batch_written += n_inserted

        total_written += batch_written
        last_block_in_batch = int(rows[-1][1])
        await _save_progress(pool, last_block_in_batch, batch_written)
        logger.info(
            "  写入 %d 行（跳过 %d 重复），累计 %d 行，water mark block=%d",
            batch_written,
            len(records) - batch_written,
            total_written,
            last_block_in_batch,
        )

        cursor = batch_end + 1

    return total_written


# ── CLI 入口 ───────────────────────────────────────────────────────────────────


async def _async_main(args: argparse.Namespace) -> None:
    cfg = load_config()
    pool = await asyncpg.create_pool(
        host=cfg.postgres.host,
        port=cfg.postgres.port,
        user=cfg.postgres.user,
        password=cfg.postgres.password,
        database=cfg.postgres.database,
        min_size=1,
        max_size=4,
    )

    try:
        # ── 建表 ──────────────────────────────────────────────────────────────
        if args.init_db:
            logger.info("建表 loan.aave_atoken_transfers ...")
            async with pool.acquire() as conn:
                await conn.execute(DDL_TRANSFERS)
                await conn.execute(DDL_INDEXES)
                await conn.execute(DDL_SYNC_META)
            logger.info("建表完成。")
            if not args.full and not args.run:
                return

        # ── 加载 aToken 地址 ───────────────────────────────────────────────
        atoken_addresses = await _load_atoken_addresses(pool, cfg.rpc_url)
        if not atoken_addresses:
            logger.error("未找到任何 aToken 地址，退出。")
            return

        # ── 确定区块范围 ───────────────────────────────────────────────────
        block_from: int | None = args.from_block
        block_to: int | None = args.to_block

        if args.full:
            logger.warning("--full 模式：清空表并从头同步")
            async with pool.acquire() as conn:
                await conn.execute("TRUNCATE loan.aave_atoken_transfers")
                await conn.execute("TRUNCATE loan.aave_atoken_transfer_sync")

        with ClickHouseClient(cfg.clickhouse) as ch:
            # 确定 end_block（链头或用户指定上限）
            if block_to is not None:
                end_block = block_to
            else:
                r = ch.query(f"SELECT max(BlockNumber) FROM {CH_TABLE}")
                end_block = int(r[0][0])

            # 确定 start_block
            if block_from is not None:
                # 区块范围模式：忽略水位线，直接用用户指定值
                start_block = block_from
            elif args.full:
                r = ch.query(f"SELECT min(BlockNumber) FROM {CH_TABLE}")
                start_block = int(r[0][0])
            else:
                # 增量模式：从水位线 +1 继续
                last = await _get_last_block(pool)
                start_block = (
                    last + 1
                    if last > 0
                    else (
                        int(ch.query(f"SELECT min(BlockNumber) FROM {CH_TABLE}")[0][0])
                    )
                )

            logger.info(
                "同步区块范围 [%d, %d]  共 %d 个区块",
                start_block,
                end_block,
                end_block - start_block + 1,
            )

            total = await _sync(
                pool=pool,
                ch=ch,
                atoken_addresses=atoken_addresses,
                start_block=start_block,
                end_block=end_block,
            )

        logger.info("同步完成，共写入 %d 行。", total)

    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="同步 ClickHouse aToken Transfer 事件到 PostgreSQL"
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="建表（idempotent），可与 --full/--run 组合",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="清空并全量重新同步",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="在 --init-db 后继续执行同步（默认仅建表后退出）",
    )
    parser.add_argument(
        "--from-block",
        type=int,
        default=None,
        metavar="BLOCK",
        help="只同步 BlockNumber >= BLOCK 的事件（覆盖水位线）",
    )
    parser.add_argument(
        "--to-block",
        type=int,
        default=None,
        metavar="BLOCK",
        help="只同步 BlockNumber <= BLOCK 的事件",
    )
    args = parser.parse_args()

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
