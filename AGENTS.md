# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Aave V2/V3 Ethereum Mainnet liquidation monitoring system. Crawls user positions (collateral/borrow), calculates ETH liquidation prices for both long positions (ETH price drop risk) and short positions (ETH price rise risk for WETH borrowers).

**Architecture**: Python backend (FastAPI + asyncpg/SQLAlchemy + web3.py) + React frontend (TypeScript + Vite) + PostgreSQL + ClickHouse (for raw blockchain logs).

## Development Commands

### Backend (Python 3.12+, uv package manager)

```bash
cd backend

# Install dependencies
uv sync

# Run CLI commands
uv run aave-crawler sync-addresses              # Derive user addresses from history
uv run aave-crawler crawl -p v3                 # Crawl V3 collateral positions
uv run aave-crawler crawl -p v3_borrow          # Crawl V3 borrow positions
uv run aave-crawler watch -p v3                 # Watch mode (continuous)
uv run aave-crawler check 0xAddress             # Debug single address

# Start API server
uv run api                                      # Default: 0.0.0.0:8000
uv run api --reload                             # Dev mode with hot reload
uv run api --port 8080 --workers 4              # Production

# Database migrations (Alembic)
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
uv run alembic downgrade -1

# Testing
uv run pytest tests/ -q
uv run pytest tests/test_routes.py -v

# Type checking and linting (via pre-commit)
pre-commit run --all-files
```

### Frontend (Node.js 18+, pnpm)

```bash
cd frontend

# Install dependencies
pnpm install

# Development
pnpm dev                    # Local only
pnpm dev --host             # LAN access

# Production build
pnpm build                  # Output: dist/
pnpm preview                # Preview production build
```

### Configuration Files

- `backend/config.yaml` - Backend config (RPC, PostgreSQL, ClickHouse, crawler settings)
- `frontend/.env.local` - Frontend API endpoint override (VITE_API_BASE_URL)

Both files are gitignored. Copy from `.example` files and modify.

## Architecture Patterns

### Dual Database Access Pattern

The backend uses **two PostgreSQL client libraries** for different use cases:

1. **asyncpg** (`db.py`) - High-performance scenarios:
   - Batch writes via native `COPY` protocol (10-50x faster than ORM)
   - Complex transactions requiring explicit connection control
   - Performance-critical queries (e.g., `simulate_liquidation_period`)
   - Injected via `AsyncpgPool = Annotated[asyncpg.Pool, Depends(get_pool)]`

2. **SQLAlchemy AsyncSession** (`database.py`, `orm_models.py`) - Type-safe queries:
   - API layer read operations (`api/routes.py`, `api/service.py`)
   - Provides full type hints and IDE autocomplete
   - Alembic migration source of truth
   - Injected via `DbSession = Annotated[AsyncSession, Depends(get_db)]`

**Rule**: Use SQLAlchemy for API queries unless performance profiling shows a bottleneck. Use asyncpg for batch operations and crawler writes.

### Protocol Table Structure

Four table sets per protocol version (v2/v3):

```text
loan.aave_{v2|v3}_eth_positions_collateral          # Collateral-side summary
loan.aave_{v2|v3}_eth_positions_borrow              # Borrow-side summary
loan.aave_{v2|v3}_eth_reserve_positions_collateral  # Per-reserve details
loan.aave_{v2|v3}_eth_reserve_positions_borrow      # Per-reserve details
```

Source tables (user address lists):

```text
loan.aave_{v2|v3}_eth_weth_collateral
loan.aave_{v2|v3}_eth_weth_borrow
```

**Naming convention**: `_eth_` infix indicates ETH-related assets only (WETH, wstETH, rETH, etc.). Market-wide tables omit this infix (e.g., `aave_v3_market_snapshots`).

### Oracle Price Handling

Critical difference between protocol versions:

- **Aave V3**: Oracle returns USD price with 8 decimals → `oracle_price_in_eth=False`
- **Aave V2**: Oracle returns ETH price with 18 decimals → `oracle_price_in_eth=True`
  - Must multiply by ETH/USD to get USD price
  - For historical blocks: use Chainlink ETH/USD (available from 2019), fallback to V3 oracle

See `rpc.py:fetch_user_position()` and `rpc.py:fetch_user_position_at_block()` for implementation.

### ETH Asset Symbols

Defined in `constants.py:ETH_SYMBOLS`:

```python
ETH_SYMBOLS = {"WETH", "wstETH", "rETH", "cbETH", "WSTETH"}
```

Used for:

- Filtering collateral positions (ETH downside risk)
- Filtering borrow positions (WETH upside risk)
- Address derivation from `aave.aave_history`

### Liquidation Price Calculation

Two directions:

1. **Collateral side** (`liq_price`): ETH price drop triggers liquidation
   - Calculated when user has ETH collateral + any debt
   - Formula: `liq_price = total_debt_usd / (eth_collateral_amount * liq_threshold)`

2. **Borrow side** (`liq_price_rise`): ETH price rise triggers liquidation
   - Calculated when user borrows WETH with non-ETH collateral
   - Formula: `liq_price_rise = (total_collateral_usd * liq_threshold) / weth_debt_amount`

Both stored in position tables. Zero value means no liquidation risk in that direction.

## Key File Locations

### Backend Core

- `aave_crawler/cli.py` - Click CLI entry point (all commands)
- `aave_crawler/server.py` - FastAPI app factory + uvicorn entry
- `aave_crawler/config.py` - Config loading (AppConfig, PostgresConfig, ClickHouseConfig)
- `aave_crawler/rpc.py` - Web3 contract calls (fetch_user_position, fetch_user_position_at_block)
- `aave_crawler/db.py` - asyncpg layer (DDL, UPSERT, sync_addresses_from_history)
- `aave_crawler/database.py` - SQLAlchemy session management
- `aave_crawler/orm_models.py` - SQLAlchemy ORM models (Alembic migration source)
- `aave_crawler/models.py` - Pure dataclasses (UserPosition, ReserveConfig)
- `aave_crawler/crawler.py` - Batch crawl main loop
- `aave_crawler/watcher.py` - Incremental watch mode
- `aave_crawler/clickhouse.py` - ClickHouse HTTP client (reads eth_defi.rrmt_logs)
- `aave_crawler/constants.py` - ETH_SYMBOLS, MAX_UINT256, MAX_HF, LIQ_PRICE_CAP

### Backend API

- `aave_crawler/api/routes.py` - FastAPI route definitions
- `aave_crawler/api/service.py` - Business logic layer
- `aave_crawler/api/schemas.py` - Pydantic response models

### Frontend

- `src/App.tsx` - Root component (tabs, protocol/side toggles, routing)
- `src/components/AddressInput.tsx` - Address input with viem validation
- `src/components/SummaryCard.tsx` - Account overview card
- `src/components/PositionTable.tsx` - Asset/liability detail tables
- `src/components/MarketAssessment.tsx` - Market-wide analysis container
- `src/components/LiquidationChart.tsx` - Liquidation distribution bar chart
- `src/components/EthPriceTrend.tsx` - ETH price history line chart

### Database

- `alembic/versions/` - Migration scripts
- `alembic.ini` - Alembic configuration

## Important Patterns

### CLI Protocol Parameter

The `-p/--protocol` flag accepts four values:

- `v2` - Aave V2 collateral side
- `v3` - Aave V3 collateral side (default)
- `v2_borrow` - Aave V2 borrow side
- `v3_borrow` - Aave V3 borrow side

This maps to `ProtocolTables` in `db.py` which defines table names for each combination.

### Config Loading Priority

`config.py:load_config()` searches in order:

1. Explicitly passed path
2. Current working directory `config.yaml`
3. `backend/config.yaml` (relative to package)

### Database Connection Injection

FastAPI routes use dependency injection:

```python
from aave_crawler.database import get_db, get_pool

async def route(
    db: DbSession,              # SQLAlchemy AsyncSession
    pool: AsyncpgPool,          # asyncpg Pool
):
    # Use db for ORM queries
    # Use pool for raw SQL / COPY operations
```

### ClickHouse Log Querying

`eth_defi.rrmt_logs` table stores all Ethereum event logs. Key columns:

- `TopicHash` - Event signature (topic[0]), lowercase with 0x prefix
- `Address` - Contract address, lowercase with 0x prefix
- `Topics` - Comma-separated topic[1..N] (each 32-byte padded hex)
- `Data` - ABI-encoded event data

Example: Query aToken Transfer events:

```sql
WHERE TopicHash = '0xddf252ad...' AND Address = '0x4d5f47fa...'
```

Extract addresses from Topics: `splitByChar(',', Topics)[1]` gives padded from address.

## Testing

Backend tests (`tests/`) use pytest with full mocking - no real database or RPC required. See `tests/conftest.py` for fixtures.

Frontend has no test suite currently.

## Deployment Notes

- Backend: Typical workflow is `sync-addresses` → `crawl` (all 4 sides) → `watch` (background) → `api`
- Frontend: Static build in `dist/`, requires `VITE_API_BASE_URL` set at build time
- Database: Requires PostgreSQL with `aave.aave_history` table (maintained by external chain-data-collector)
- ClickHouse: Optional, only needed for aToken transfer analysis (not core functionality)

## Common Gotchas

1. **Alembic migrations**: Only cover `loan` schema. Other schemas (e.g., `aave`) are external.
2. **Health factor infinity**: Stored as `1e18` in database (MAX_HF constant) when user has no debt.
3. **Liquidation price cap**: Set to `1e9` (LIQ_PRICE_CAP) to prevent overflow in edge cases.
4. **Address case sensitivity**: Database stores lowercase. API accepts both checksummed and lowercase.
5. **Oracle price units**: Always check `oracle_price_in_eth` parameter when calling RPC functions.
6. **Incremental crawl**: Use `--incremental` flag to skip already-crawled addresses (checks target table).
7. **Watch mode water mark**: Stored in `loan.watcher_watermarks` table, tracks last processed timestamp.
