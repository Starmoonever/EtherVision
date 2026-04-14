from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from justlend_crawler.api import service
from justlend_crawler import rpc as justlend_rpc


def _mock_replay_tx_row(
    *,
    tx_hash: bytes | None = None,
    block_number: int = 123,
    method_id: str = "a0712d68",
    block_timestamp: datetime | None = None,
    contract_address: str | None = "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
    parse_summary: str = "",
    parse_input: str = "",
    contract_type: int | None = 31,
) -> dict[str, object]:
    return {
        "tx_hash": tx_hash or bytes.fromhex("11" * 32),
        "block_number": block_number,
        "block_timestamp": block_timestamp
        or datetime(2026, 4, 3, 9, 49, 31, tzinfo=timezone.utc),
        "method_id": method_id,
        "contract": (
            json.dumps({"contract_address": contract_address})
            if contract_address is not None
            else None
        ),
        "parse_summary": parse_summary,
        "parse_input": parse_input,
        "contract_type": contract_type,
    }


def _mock_event_snapshot_row(
    *,
    user_address: bytes,
    tx_hash: bytes | None = None,
    block_number: int = 123,
    block_timestamp: datetime | None = None,
    market: bytes | None = None,
    symbol: str | None = "JST",
    operation_type: str | None = "deposit",
    brief: str = "存入 JST 仓位",
    assets_jsonb: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": 1,
        "user_address": user_address,
        "chain": "tron",
        "protocol": "trx",
        "tx_hash": (tx_hash or bytes.fromhex("11" * 32)).hex(),
        "block_number": block_number,
        "block_timestamp": block_timestamp
        or datetime(2026, 4, 3, 9, 49, 31, tzinfo=timezone.utc),
        "market": market,
        "symbol": symbol,
        "method_id": "a0712d68",
        "operation_type": operation_type,
        "has_open_position": True,
        "is_liquidatable": False,
        "total_collateral_usd": Decimal("100"),
        "total_debt_usd": Decimal("20"),
        "available_borrow_usd": Decimal("55"),
        "discounted_collateral_usd": Decimal("75"),
        "liquidation_buffer_usd": Decimal("55"),
        "health_factor": Decimal("5"),
        "ltv": Decimal("0.2"),
        "liquidation_threshold": Decimal("0.75"),
        "assets_jsonb": assets_jsonb or [],
        "extra_jsonb": {},
        "brief": brief,
    }


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
            "_persist_position_snapshot",
            new=AsyncMock(),
        ) as persist,
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
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_position_replay_returns_cached_snapshots() -> None:
    user_address = bytes.fromhex("41d148e2b66c5d5979fe1f7f4b2a791ef6ab733e8a")
    snapshots = [
        _mock_event_snapshot_row(
            user_address=user_address,
            market=service._tron_address_to_bytes("TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9"),
            brief="存入 JST 后，抵押 $100.00000000，债务 $20.00000000，HF 5.000000000000000000",
            assets_jsonb=[
                {
                    "asset_address": "TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9",
                    "side": "collateral",
                    "symbol": "JST",
                    "amount": "12",
                    "price_usd": "2",
                    "value_usd": "24",
                }
            ],
        )
    ]

    with (
        patch.object(
            service,
            "get_justlend_event_snapshots",
            new=AsyncMock(return_value=snapshots),
        ) as fetch_snapshots,
        patch.object(
            service,
            "fetch_justlend_user_tx_history",
            new=AsyncMock(
                return_value=[
                    _mock_replay_tx_row(
                        contract_address="TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9"
                    )
                ]
            ),
        ),
    ):
        result = await service.get_position_replay(
            pool=cast(asyncpg.Pool, object()),
            cfg=SimpleNamespace(
                justlend=SimpleNamespace(
                    api_base_url="https://api.justlend.invalid",
                    api_timeout_seconds=3.0,
                    markets=[],
                )
            ),
            tron_rpc=None,
            address="TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ",
            protocol="trx",
            from_ts=int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()),
            to_ts=int(datetime(2026, 4, 5, tzinfo=timezone.utc).timestamp()),
            use_cache=True,
            detail=True,
        )

    assert result.data_source == "cache"
    assert result.cache_hit_rate == "1.00"
    assert result.total_points == 1
    assert result.total_tx_count == 1
    assert result.points[0].brief.startswith("存入 JST")
    assert result.points[0].assets[0].symbol == "JST"
    assert result.points[0].tx_hash == "11" * 32
    fetch_snapshots.assert_awaited_once()


def test_build_tx_brief_prefers_parse_summary_amount_symbol() -> None:
    brief = service._build_tx_brief(
        method_id="a0712d68",
        market="TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9",
        parse_summary="Mint 12.5 JST to supply",
        parse_input="",
    )
    assert brief == "存入 12.5 JST"


def test_build_tx_brief_from_delta_includes_usd_value() -> None:
    brief = service._build_tx_brief_from_delta(
        tx={
            "method_id": "a0712d68",
            "market": None,
            "parse_summary": "",
            "parse_input": "",
        },
        amount=Decimal("1.5"),
        meta={"underlying_symbol": "USDT", "price_usd": Decimal("1")},
    )
    assert brief == "存入 1.5 USDT (价值 1.50 usd)"


def test_normalize_tron_address_prefers_base58() -> None:
    expected = "TFxKt6qB8DJpHke6an8iBuc11dtMKywfsy"
    assert (
        service._normalize_tron_address("4141a614f803b6fd780986a42c78ec9c7f77e6ded3")
        == expected
    )
    assert (
        service._normalize_tron_address(
            bytes.fromhex("4141a614f803b6fd780986a42c78ec9c7f77e6ded3")
        )
        == expected
    )


def test_normalize_asset_items_accepts_json_string_payload() -> None:
    items = service._normalize_asset_items(
        '[{"asset_address":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t","symbol":"USDT","side":"borrow","amount":"1","price_usd":"1","value_usd":"1"}]'
    )
    assert len(items) == 1
    assert items[0]["symbol"] == "USDT"


def test_build_tx_brief_falls_back_to_parse_summary_text() -> None:
    brief = service._build_tx_brief(
        method_id="c5ebeaec",
        market=None,
        parse_summary="Borrow operation executed",
        parse_input="",
    )
    assert brief == "Borrow operation executed"


def test_normalize_replay_txs_falls_back_to_parse_input_asset_for_market() -> None:
    txs = service._normalize_replay_txs(
        [
            _mock_replay_tx_row(
                contract_address=None,
                parse_input=json.dumps(
                    {
                        "asset": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
                        "amount": "1000000",
                        "summary": "Borrow",
                    }
                ),
            )
        ]
    )

    assert len(txs) == 1
    assert txs[0]["market"] == "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"


def test_normalize_replay_txs_filters_non_trigger_smart_contract() -> None:
    txs = service._normalize_replay_txs(
        [
            _mock_replay_tx_row(
                contract_type=1,
                parse_input='{"asset":"TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"}',
            )
        ]
    )
    assert txs == []


def test_parse_tx_delta_supports_underlying_alias_and_returns_symbol_meta() -> None:
    market_hex = service._tron_address_to_bytes(
        "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"
    ).hex()
    underlying_hex = service._tron_address_to_bytes(
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    ).hex()
    catalog_entry = {
        "market_address": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
        "market_hex": market_hex,
        "underlying_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "underlying_hex": underlying_hex,
        "underlying_symbol": "USDT",
        "underlying_decimals": 6,
        "collateral_factor": Decimal("0.8"),
        "price_usd": Decimal("1"),
        "exchange_rate": None,
    }
    tx = {
        "method_id": "a0712d68",
        "parse_input": json.dumps(
            {"asset": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "amount": "1500000"}
        ),
    }

    market_key, amount, operation_type, meta = service._parse_tx_delta(
        tx,
        {market_hex: catalog_entry, underlying_hex: catalog_entry},
    )

    assert market_key == market_hex
    assert amount == Decimal("1.5")
    assert operation_type == "deposit"
    assert meta is catalog_entry


def test_build_event_snapshot_row_sets_symbol_open_position_and_detailed_brief() -> (
    None
):
    user_address = service._tron_address_to_bytes("TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ")
    market_hex = service._tron_address_to_bytes(
        "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"
    ).hex()
    catalog_entry = {
        "market_address": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
        "market_hex": market_hex,
        "underlying_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "underlying_hex": service._tron_address_to_bytes(
            "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        ).hex(),
        "underlying_symbol": "USDT",
        "underlying_decimals": 6,
        "collateral_factor": Decimal("0.8"),
        "price_usd": Decimal("1"),
        "exchange_rate": None,
    }
    tx = {
        "tx_hash": "11" * 32,
        "method_id": "a0712d68",
        "block_number": 123,
        "block_timestamp": datetime(2026, 4, 3, 9, 49, 31, tzinfo=timezone.utc),
        "market": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "_meta": catalog_entry,
        "_brief": "存入 1.5 USDT (价值 1.50 usd)",
        "parse_summary": "",
        "parse_input": "",
    }

    row = service._build_event_snapshot_row(
        user_address=user_address,
        tx=tx,
        balances={market_hex: {"supply": Decimal("1.5"), "borrow": Decimal("0")}},
        market_catalog={market_hex: catalog_entry},
    )

    assert row.symbol == "USDT"
    assert row.has_open_position is True
    assert row.total_collateral_usd == Decimal("1.5")
    assert row.brief == "存入 1.5 USDT (价值 1.50 usd)"


@pytest.mark.asyncio
async def test_get_position_replay_raises_when_historical_window_has_no_cached_snapshots() -> (
    None
):
    with (
        patch.object(
            service,
            "get_justlend_event_snapshots",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            service,
            "fetch_justlend_user_tx_history",
            new=AsyncMock(return_value=[_mock_replay_tx_row()]),
        ),
        patch.object(
            service,
            "_collect_and_cache_replay_misses",
            new=AsyncMock(return_value=[]),
        ),
    ):
        with pytest.raises(service.HTTPException) as exc_info:
            await service.get_position_replay(
                pool=cast(asyncpg.Pool, object()),
                cfg=SimpleNamespace(
                    justlend=SimpleNamespace(
                        api_base_url="https://api.justlend.invalid",
                        api_timeout_seconds=3.0,
                        markets=[],
                    )
                ),
                tron_rpc=None,
                address="TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ",
                protocol="trx",
                from_ts=int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()),
                to_ts=int(datetime(2026, 4, 10, tzinfo=timezone.utc).timestamp()),
                use_cache=True,
                detail=False,
            )

    assert exc_info.value.status_code == 501
    assert "无法重建" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_position_replay_raises_when_transaction_cache_missing() -> None:
    user_address = bytes.fromhex("41d148e2b66c5d5979fe1f7f4b2a791ef6ab733e8a")
    rebuilt_rows = [
        _mock_event_snapshot_row(
            user_address=user_address,
            market=service._tron_address_to_bytes("TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"),
            operation_type="deposit",
            brief="存入 10 JST",
        )
    ]
    with (
        patch.object(
            service,
            "get_justlend_event_snapshots",
            new=AsyncMock(return_value=[]),
        ) as get_cached,
        patch.object(
            service,
            "fetch_justlend_user_tx_history",
            new=AsyncMock(return_value=[_mock_replay_tx_row()]),
        ),
        patch.object(
            service,
            "_collect_and_cache_replay_misses",
            new=AsyncMock(return_value=rebuilt_rows),
        ) as rebuild,
    ):
        result = await service.get_position_replay(
            pool=cast(asyncpg.Pool, object()),
            cfg=SimpleNamespace(
                justlend=SimpleNamespace(
                    api_base_url="https://api.justlend.invalid",
                    api_timeout_seconds=3.0,
                    markets=[],
                )
            ),
            tron_rpc=None,
            address="TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ",
            protocol="trx",
            from_ts=int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()),
            to_ts=int(datetime(2099, 4, 5, tzinfo=timezone.utc).timestamp()),
            use_cache=True,
            detail=False,
        )

    assert result.data_source == "api"
    assert result.total_points == 1
    assert result.total_tx_count == 1
    rebuild.assert_awaited_once()
    assert get_cached.await_count == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_fetch_position_from_tron_rpc_matches_api_summary() -> None:
    market_a = "411111111111111111111111111111111111111111"
    market_b = "412222222222222222222222222222222222222222"
    underlying_a = "413333333333333333333333333333333333333333"
    underlying_b = "414444444444444444444444444444444444444444"
    market_a_b58 = justlend_rpc._hex_to_tron_base58(market_a)
    market_b_b58 = justlend_rpc._hex_to_tron_base58(market_b)
    underlying_a_b58 = justlend_rpc._hex_to_tron_base58(underlying_a)
    underlying_b_b58 = justlend_rpc._hex_to_tron_base58(underlying_b)
    user_address = "TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ"

    market_payload = {
        "code": 0,
        "data": {
            "tokenList": [
                {
                    "address": market_a,
                    "underlyingAddress": underlying_a,
                    "underlyingSymbol": "JST",
                    "underlyingDecimal": 18,
                    "underlyingPriceInTrx": "0.25",
                    "collateralFactor": "0.5",
                },
                {
                    "address": market_b,
                    "underlyingAddress": underlying_b,
                    "underlyingSymbol": "USDT",
                    "underlyingDecimal": 6,
                    "underlyingPriceInTrx": "0.5",
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
                    "address": user_address,
                    "totalCollateralValueInTrx": "0",
                    "totalBorrowValueInTrx": "0",
                    "tokens": [
                        {
                            "address": market_a,
                            "underlyingSymbol": "JST",
                            "supplyBalanceUnderlying": "100",
                            "borrowBalanceUnderlying": "0",
                            "entered": True,
                        },
                        {
                            "address": market_b,
                            "underlyingSymbol": "USDT",
                            "supplyBalanceUnderlying": "0",
                            "borrowBalanceUnderlying": "20",
                            "entered": False,
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
        api_result = await service.fetch_position_from_justlend_api(
            user_address,
            api_base_url="https://api.justlend.invalid",
            timeout=3.0,
        )

    def _address_response(function_selector: str, contract_address: str) -> str:
        if function_selector == "comptroller()":
            return justlend_rpc._hex_to_tron_base58(
                "41aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            )
        if function_selector == "oracle()":
            return justlend_rpc._hex_to_tron_base58(
                "41bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )
        if function_selector == "underlying()":
            if contract_address == market_a_b58:
                return underlying_a_b58
            if contract_address == market_b_b58:
                return underlying_b_b58
        raise AssertionError((function_selector, contract_address))

    def _string_response(function_selector: str, contract_address: str) -> str:
        if function_selector == "symbol()":
            mapping = {
                market_a_b58: "jJST",
                market_b_b58: "jUSDT",
                underlying_a_b58: "JST",
                underlying_b_b58: "USDT",
            }
            return mapping[contract_address]
        raise AssertionError((function_selector, contract_address))

    async def _mock_call_account_snapshot(*args, **kwargs):
        contract_address = kwargs["contract_address"]
        if contract_address == market_a_b58:
            return (0, 100 * 10**8, 0, 10**18)
        if contract_address == market_b_b58:
            return (0, 0, 20 * 10**6, 10**18)
        raise AssertionError(contract_address)

    async def _mock_call_address(*args, **kwargs):
        return _address_response(
            kwargs["function_selector"], kwargs["contract_address"]
        )

    async def _mock_call_market_config(*args, **kwargs):
        market_address = kwargs["market_address"]
        if market_address == market_a_b58:
            return True, Decimal("0.5")
        if market_address == market_b_b58:
            return False, Decimal("0.8")
        raise AssertionError(market_address)

    async def _mock_call_uint256(*args, **kwargs):
        contract_address = kwargs["contract_address"]
        function_selector = kwargs["function_selector"]
        if function_selector == "getUnderlyingPrice(address)":
            parameter = kwargs["parameter"]
            if parameter.endswith(market_a):
                return 250000000000000000
            if parameter.endswith(market_b):
                return 500000000000000000000000000000
        if function_selector == "decimals()":
            if contract_address == underlying_a_b58:
                return 18
            if contract_address == underlying_b_b58:
                return 6
        raise AssertionError((function_selector, contract_address, kwargs))

    async def _mock_call_string(*args, **kwargs):
        return _string_response(kwargs["function_selector"], kwargs["contract_address"])

    with (
        patch.object(
            justlend_rpc,
            "_call_account_snapshot",
            new=AsyncMock(side_effect=_mock_call_account_snapshot),
        ),
        patch.object(
            justlend_rpc,
            "_call_address",
            new=AsyncMock(side_effect=_mock_call_address),
        ),
        patch.object(
            justlend_rpc,
            "_call_market_config",
            new=AsyncMock(side_effect=_mock_call_market_config),
        ),
        patch.object(
            justlend_rpc,
            "_call_uint256",
            new=AsyncMock(side_effect=_mock_call_uint256),
        ),
        patch.object(
            justlend_rpc,
            "_call_string",
            new=AsyncMock(side_effect=_mock_call_string),
        ),
    ):
        rpc_result = await justlend_rpc.fetch_justlend_position_via_rpc(
            tron_rpc=object(),  # type: ignore[arg-type]
            address=user_address,
            protocol="trx",
            market_addresses=[market_a, market_b],
        )

    assert rpc_result["total_collateral_usd"] == api_result["total_collateral_usd"]
    assert rpc_result["total_debt_usd"] == api_result["total_debt_usd"]
    assert rpc_result["available_borrow_usd"] == api_result["available_borrow_usd"]
    assert rpc_result["health_factor"] == api_result["health_factor"]
    assert rpc_result["ltv"] == api_result["ltv"]
    assert rpc_result["liquidation_threshold"] == api_result["liquidation_threshold"]
    assert len(rpc_result["assets"]) == len(api_result["assets"])
    assert rpc_result["extra_jsonb"]["source"] == "justlend_rpc"
