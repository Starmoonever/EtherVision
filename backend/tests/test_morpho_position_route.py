from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from morpho_crawler.api.routes import router as morpho_router
from morpho_crawler.api.schemas import (
    MorphoPositionAssetResponse,
    MorphoPositionResponse,
)


def _build_client(*, with_w3: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(morpho_router)
    if with_w3:
        app.state.w3 = object()
    return TestClient(app)


def _mock_position() -> MorphoPositionResponse:
    return MorphoPositionResponse(
        protocol="morpho",
        market_type="blue",
        chain="ethereum",
        morpho_address="0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb",
        market_id="0x" + "11" * 32,
        address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        block_number=123,
        block_timestamp="2026-04-08T00:00:00Z",
        has_position=True,
        is_healthy=True,
        loan_token="0x1111111111111111111111111111111111111111",
        loan_token_symbol="USDC",
        loan_token_decimals=6,
        collateral_token="0x2222222222222222222222222222222222222222",
        collateral_token_symbol="wstETH",
        collateral_token_decimals=18,
        oracle="0x3333333333333333333333333333333333333333",
        irm="0x4444444444444444444444444444444444444444",
        lltv=str(86 * 10**16),
        lltv_ratio="0.860000",
        supply_shares="0",
        borrow_shares="1000",
        collateral_assets_raw="2000",
        supply_assets="0",
        borrow_assets="1",
        collateral_assets="2",
        collateral_value_in_loan_asset="3",
        max_borrowable_in_loan_asset="2.58",
        health_factor="2.580000000000000000",
        price_quote="1.500000000000000000",
        data_source="rpc",
        assets=[
            MorphoPositionAssetResponse(
                role="loan",
                token_address="0x1111111111111111111111111111111111111111",
                symbol="USDC",
                decimals=6,
                amount="-1",
            ),
            MorphoPositionAssetResponse(
                role="collateral",
                token_address="0x2222222222222222222222222222222222222222",
                symbol="wstETH",
                decimals=18,
                amount="2",
            ),
        ],
    )


def test_morpho_position_ok() -> None:
    with _build_client() as client:
        with patch(
            "morpho_crawler.api.routes.get_user_position",
            new_callable=AsyncMock,
            return_value=_mock_position(),
        ) as mocked:
            resp = client.get(
                "/api/morpho/position",
                params={
                    "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "market_id": "0x" + "11" * 32,
                },
            )

    assert resp.status_code == 200
    mocked.assert_awaited_once()
    payload = resp.json()
    assert payload["protocol"] == "morpho"
    assert payload["market_id"] == "0x" + "11" * 32
    assert payload["data_source"] == "rpc"


def test_morpho_position_requires_w3() -> None:
    with _build_client(with_w3=False) as client:
        resp = client.get(
            "/api/morpho/position",
            params={
                "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "market_id": "0x" + "11" * 32,
            },
        )
    assert resp.status_code == 503


def test_morpho_position_propagates_http_error() -> None:
    with _build_client() as client:
        with patch(
            "morpho_crawler.api.routes.get_user_position",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=404, detail="morpho market not found"
            ),
        ):
            resp = client.get(
                "/api/morpho/position",
                params={
                    "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "market_id": "0x" + "11" * 32,
                },
            )

    assert resp.status_code == 404
