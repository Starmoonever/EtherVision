from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from makerdao_crawler.api import service as makerdao_service
from makerdao_crawler.api.routes import router as makerdao_router
from makerdao_crawler.api.schemas import (
    MakerDaoPositionAssetResponse,
    MakerDaoVaultPositionItemResponse,
    MakerDaoVaultPositionResponse,
)
from makerdao_crawler.database import get_pool

from tests.helpers.routes import build_test_client


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, ilks=None, positions=None):
        self._ilks = ilks or []
        self._positions = positions or []

    async def fetch(self, sql, *_args):
        if "FROM loan.makerdao_ilks_current" in sql:
            return self._ilks
        if "FROM loan.makerdao_current_vault_positions" in sql:
            return self._positions
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def _build_client(*, ilks=None, positions=None):
    fake_pool = _FakePool(_FakeConn(ilks=ilks, positions=positions))

    async def _override_pool():
        return fake_pool

    return build_test_client(
        router=makerdao_router,
        dependency_overrides={get_pool: _override_pool},
    )


def test_status_route_returns_scaffold_metadata() -> None:
    with _build_client() as client:
        response = client.get("/api/makerdao/status")

    assert response.status_code == 200
    assert response.json() == {
        "module": "makerdao",
        "status": "live-position",
        "chain": "ethereum",
        "supported_protocols": ["vault"],
        "message": "MakerDAO current vault position API is wired for live on-chain reads. Replay and liquidation event parsing are pending.",
    }


def test_ilks_route_returns_cached_ilks() -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    row = {
        "ilk": "ETH-A",
        "vault_type": "vault",
        "gem_symbol": "WETH",
        "gem_address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
        "debt_ceiling": "100000000",
        "liquidation_ratio": "1.45",
        "liquidation_penalty": "0.13",
        "stability_fee": "0.05",
        "dust": "5000",
        "updated_at": ts,
    }
    with _build_client(ilks=[row]) as client:
        response = client.get("/api/makerdao/ilks")

    assert response.status_code == 200
    assert response.json() == {
        "chain": "ethereum",
        "protocol": "makerdao",
        "ilks": [
            {
                "ilk": "ETH-A",
                "vault_type": "vault",
                "gem_symbol": "WETH",
                "gem_address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
                "debt_ceiling": "100000000",
                "liquidation_ratio": "1.45",
                "liquidation_penalty": "0.13",
                "stability_fee": "0.05",
                "dust": "5000",
                "updated_at": "2026-04-23T10:00:00Z",
            }
        ],
    }


def test_position_route_returns_live_vault_positions(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_get_user_vault_position(**kwargs):
        assert kwargs["address"] == "0x2222222222222222222222222222222222222222"
        assert kwargs["vault_id"] is None
        assert kwargs["ilk"] is None
        assert kwargs["include_empty"] is False
        return MakerDaoVaultPositionResponse(
            chain="ethereum",
            protocol="makerdao",
            address="0x2222222222222222222222222222222222222222",
            total_positions=1,
            positions=[
                MakerDaoVaultPositionItemResponse(
                    vault_uid="ethereum:makerdao:12345",
                    vault_id=12345,
                    vault_type="vault",
                    ilk="ETH-A",
                    urn_address="0x1111111111111111111111111111111111111111",
                    owner_address="0x2222222222222222222222222222222222222222",
                    proxy_address="0x3333333333333333333333333333333333333333",
                    block_number=22334455,
                    block_timestamp=ts.isoformat().replace("+00:00", "Z"),
                    snapshot_at=ts.isoformat().replace("+00:00", "Z"),
                    collateral_symbol="WETH",
                    collateral_token_address="0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
                    collateral_amount="12.5",
                    collateral_value_usd="40000",
                    debt_symbol="DAI",
                    debt_token_address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
                    debt_amount="18000",
                    debt_value_usd="18000",
                    liquidation_ratio="1.45",
                    liquidation_price_usd="2088.88",
                    health_factor="2.22",
                    is_healthy=True,
                    data_source="onchain-live",
                    assets=[
                        MakerDaoPositionAssetResponse(
                            role="collateral",
                            token_address="0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
                            symbol="WETH",
                            amount="12.5",
                            value_usd="40000",
                        ),
                        MakerDaoPositionAssetResponse(
                            role="debt",
                            token_address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
                            symbol="DAI",
                            amount="18000",
                            value_usd="18000",
                        ),
                    ],
                )
            ],
        )

    monkeypatch.setattr(
        makerdao_service,
        "get_user_vault_position",
        _fake_get_user_vault_position,
    )

    with _build_client() as client:
        response = client.get(
            "/api/makerdao/position",
            params={"address": "0x2222222222222222222222222222222222222222"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chain"] == "ethereum"
    assert payload["protocol"] == "makerdao"
    assert payload["address"] == "0x2222222222222222222222222222222222222222"
    assert payload["total_positions"] == 1
    assert payload["positions"][0]["vault_uid"] == "ethereum:makerdao:12345"
    assert payload["positions"][0]["ilk"] == "ETH-A"
    assert payload["positions"][0]["liquidation_price_usd"] == "2088.88"
    assert payload["positions"][0]["data_source"] == "onchain-live"
    assert payload["positions"][0]["assets"][0]["role"] == "collateral"
    assert payload["positions"][0]["assets"][1]["role"] == "debt"


def test_fmt_decimal_handles_values_larger_than_default_decimal_precision() -> None:
    value = Decimal("123456789012345678901234567890.123456789012345678")

    assert (
        makerdao_service._fmt_decimal(value)
        == "123456789012345678901234567890.123456789012345678"
    )
