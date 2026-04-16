from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from morpho_crawler.api.routes import router as morpho_router
from morpho_crawler.api.schemas import MorphoPositionReplayResponse


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(morpho_router)
    app.state.w3 = object()
    app.state.pool = object()
    return TestClient(app)


def _mock_replay() -> MorphoPositionReplayResponse:
    return MorphoPositionReplayResponse(
        protocol="morpho",
        market_type="blue",
        chain="ethereum",
        market_id="0x" + "11" * 32,
        address="0xaAaAaAaaAaAaAaaAaAAAAAAAAaaaAaAaAaaAaaAa",
        from_time="2026-04-01T00:00:00Z",
        to_time="2026-04-02T00:00:00Z",
        data_source="rpc",
        total_points=1,
        total_tx_count=1,
        cache_hit_rate="0.00",
        points=[],
    )


def test_morpho_position_replay_ok() -> None:
    with _build_client() as client:
        with patch(
            "morpho_crawler.api.routes.get_position_replay",
            new_callable=AsyncMock,
            return_value=_mock_replay(),
        ) as mocked:
            resp = client.get(
                "/api/morpho/position/replay",
                params={
                    "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "market_id": "0x" + "11" * 32,
                    "start": "2026-04-01T00:00:00Z",
                    "end": "2026-04-02T00:00:00Z",
                },
            )

    assert resp.status_code == 200
    mocked.assert_awaited_once()
    payload = resp.json()
    assert payload["market_id"] == "0x" + "11" * 32
    assert payload["data_source"] == "rpc"


def test_morpho_position_replay_rejects_reverse_time_range() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/morpho/position/replay",
            params={
                "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "market_id": "0x" + "11" * 32,
                "start": "2026-04-02T00:00:00Z",
                "end": "2026-04-01T00:00:00Z",
            },
        )

    assert resp.status_code == 400


def test_morpho_position_replay_rejects_invalid_evm_address() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/morpho/position/replay",
            params={
                "address": "0x9BDF55AFE3832ABFF223C7D10B2AF529B395EC2489E32D872156421C32EC7A5F",
                "market_id": "0x" + "11" * 32,
                "start": "2026-04-01T00:00:00Z",
                "end": "2026-04-02T00:00:00Z",
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid EVM address"
