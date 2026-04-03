from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from justlend_crawler.api import service


@pytest.mark.asyncio
async def test_fetch_position_from_justlend_api_recomputes_summary_from_assets() -> (
    None
):
    market_payload = {
        "code": 0,
        "data": {
            "tokenList": [
                {
                    "address": "TJSTMarket111111111111111111111111111",
                    "underlyingAddress": "TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9",
                    "underlyingSymbol": "JST",
                    "underlyingDecimal": 18,
                    "underlyingPriceInTrx": "0.031538855",
                    "collateralFactor": "0.5",
                },
                {
                    "address": "TSUNMarket111111111111111111111111111",
                    "underlyingAddress": "TKkeiboTkxXKJpbmVFbv4a8ov5rAfRDMf9",
                    "underlyingSymbol": "SUNOLD",
                    "underlyingDecimal": 18,
                    "underlyingPriceInTrx": "8.59273987",
                    "collateralFactor": "0.6",
                },
                {
                    "address": "TUSDTMarket11111111111111111111111111",
                    "underlyingAddress": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                    "underlyingSymbol": "USDT",
                    "underlyingDecimal": 6,
                    "underlyingPriceInTrx": "0.35714285714285715",
                    "collateralFactor": "0.8",
                },
            ]
        },
    }
    account_payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "address": "TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ",
                    "totalCollateralValueInTrx": "0",
                    "totalBorrowValueInTrx": "0",
                    "tokens": [
                        {
                            "address": "TJSTMarket111111111111111111111111111",
                            "underlyingSymbol": "JST",
                            "supplyBalanceUnderlying": "3630340.439151757622965069",
                            "borrowBalanceUnderlying": "0",
                            "entered": True,
                        },
                        {
                            "address": "TSUNMarket111111111111111111111111111",
                            "underlyingSymbol": "SUNOLD",
                            "supplyBalanceUnderlying": "8340.280761299926816637",
                            "borrowBalanceUnderlying": "0",
                            "entered": True,
                        },
                    ],
                }
            ]
        },
    }

    with patch.object(
        service,
        "_fetch_json",
        new=AsyncMock(side_effect=[market_payload, account_payload]),
    ):
        result = await service.fetch_position_from_justlend_api(
            "TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ",
            api_base_url="https://api.justlend.invalid",
            timeout=3.0,
        )

    assert result["total_collateral_usd"] == Decimal("521255.4024598464239583609001")
    assert result["total_debt_usd"] == Decimal("0")
    assert result["available_borrow_usd"] == Decimal("280694.1428768156451497633172")
    assert result["health_factor"] == Decimal("1E+18")
    assert result["ltv"] == Decimal("0")
    assert result["liquidation_threshold"] == Decimal("0.5384963715525964263805347130")
    assert len(result["assets"]) == 2


@pytest.mark.asyncio
async def test_get_user_position_refreshes_invalid_cached_summary() -> None:
    user_address = bytes.fromhex("41d148e2b66c5d5979fe1f7f4b2a791ef6ab733e8a")
    cached_position = {
        "user_address": user_address,
        "chain": "tron",
        "protocol": "trx",
        "snapshot_at": datetime(2026, 4, 3, 9, 49, 31, tzinfo=timezone.utc),
        "block_timestamp": datetime(2026, 4, 3, 9, 49, 31, tzinfo=timezone.utc),
        "total_collateral_usd": Decimal("0"),
        "total_debt_usd": Decimal("0"),
        "available_borrow_usd": Decimal("0"),
        "health_factor": Decimal("0"),
        "ltv": Decimal("0"),
        "liquidation_threshold": Decimal("0"),
    }
    cached_assets = [
        {
            "asset_address": bytes.fromhex(
                "41c8599111f29c1e1e061265b4af93ea1f274ad78a"
            ),
            "side": "collateral",
            "symbol": "JST",
            "amount": Decimal("3630340.439151757622965069"),
            "price_usd": Decimal("0.06307771"),
            "value_usd": Decimal("228993.55101975"),
        }
    ]
    refreshed_position = {
        **cached_position,
        "total_collateral_usd": Decimal("228993.55101975"),
        "available_borrow_usd": Decimal("114496.77550988"),
        "health_factor": Decimal("1e18"),
        "liquidation_threshold": Decimal("0.5"),
    }
    fetched_payload = {
        "user_address": user_address,
        "chain": "tron",
        "protocol": "trx",
        "snapshot_at": datetime(2026, 4, 3, 10, 0, 0, tzinfo=timezone.utc),
        "block_timestamp": datetime(2026, 4, 3, 10, 0, 0, tzinfo=timezone.utc),
        "block_number": None,
        "source_cursor": None,
        "total_collateral_usd": Decimal("228993.55101975"),
        "total_debt_usd": Decimal("0"),
        "available_borrow_usd": Decimal("114496.77550988"),
        "health_factor": Decimal("1e18"),
        "ltv": Decimal("0"),
        "liquidation_threshold": Decimal("0.5"),
        "extra_jsonb": {"source": "justlend_api"},
        "assets": [
            {
                "asset_address": bytes.fromhex(
                    "41c8599111f29c1e1e061265b4af93ea1f274ad78a"
                ),
                "side": "collateral",
                "symbol": "JST",
                "decimals": 18,
                "amount": Decimal("3630340.439151757622965069"),
                "price_usd": Decimal("0.06307771"),
                "value_usd": Decimal("228993.55101975"),
                "extra_jsonb": {"collateral_factor": "0.5"},
            }
        ],
    }
    cfg = SimpleNamespace(
        justlend=SimpleNamespace(
            api_base_url="https://api.justlend.invalid",
            api_timeout_seconds=3.0,
        )
    )

    with (
        patch.object(
            service,
            "fetch_current_user_position",
            new=AsyncMock(
                side_effect=[
                    (cached_position, cached_assets),
                    (refreshed_position, cached_assets),
                ]
            ),
        ),
        patch.object(
            service,
            "fetch_position_from_justlend_api",
            new=AsyncMock(return_value=fetched_payload),
        ) as fetch_api,
        patch.object(
            service,
            "upsert_current_user_position",
            new=AsyncMock(),
        ) as upsert,
    ):
        result = await service.get_user_position(
            pool=cast(asyncpg.Pool, object()),
            cfg=cfg,
            address="TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ",
            protocol="trx",
        )

    assert result.data_source == "api"
    assert result.total_collateral_usd == "228993.55101975"
    assert result.health_factor == "1000000000000000000"
    fetch_api.assert_awaited_once()
    upsert.assert_awaited_once()
