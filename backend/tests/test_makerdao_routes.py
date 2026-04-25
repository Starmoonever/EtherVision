from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from makerdao_crawler.api import service as makerdao_service
from makerdao_crawler.api.routes import router as makerdao_router
from makerdao_crawler.api.schemas import (
    MakerDaoIlkDetailResponse,
    MakerDaoIlkListResponse,
    MakerDaoIlkOverviewItem,
    MakerDaoPositionAssetResponse,
    MakerDaoVaultPositionItemResponse,
    MakerDaoVaultPositionResponse,
)
from makerdao_crawler.constants import MAKERDAO_DEFAULT_CONTRACTS
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


class _FakeCall:
    def __init__(self, value):
        self._value = value

    async def call(self):
        return self._value


class _FakeFunctions:
    def __init__(self, *, ilks_value):
        self._ilks_value = ilks_value

    def ilks(self, _ilk):
        return _FakeCall(self._ilks_value)


class _FakeContract:
    def __init__(self, *, ilks_value):
        self.functions = _FakeFunctions(ilks_value=ilks_value)


class _FakeEth:
    def __init__(self, contracts):
        self._contracts = contracts

    def contract(self, *, address, abi):
        return self._contracts[address.lower()]


class _FakeWeb3:
    def __init__(self, contracts):
        self.eth = _FakeEth(contracts)


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


def test_ilks_route_returns_ilk_overview(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_get_ilks(pool, **kwargs):
        assert pool is not None
        assert "w3" in kwargs
        return MakerDaoIlkListResponse(
            chain="ethereum",
            protocol="makerdao",
            ilks=[
                MakerDaoIlkOverviewItem(
                    ilk="ETH-A",
                    vault_type="vault",
                    gem_symbol="WETH",
                    gem_address="0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
                    updated_at=ts.isoformat().replace("+00:00", "Z"),
                )
            ],
        )

    monkeypatch.setattr(makerdao_service, "get_ilks", _fake_get_ilks)

    with _build_client() as client:
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
                "updated_at": "2026-04-23T10:00:00Z",
            }
        ],
    }


def test_ilk_route_returns_ilk_detail(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_get_ilk_detail(pool, **kwargs):
        assert pool is not None
        assert kwargs["ilk"] == "ETH-A"
        assert "w3" in kwargs
        return MakerDaoIlkDetailResponse(
            chain="ethereum",
            protocol="makerdao",
            ilk="ETH-A",
            vault_type="vault",
            gem_symbol="WETH",
            gem_address="0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
            debt_ceiling="100000000",
            liquidation_ratio="1.45",
            liquidation_penalty="0.13",
            stability_fee=None,
            dust="5000",
            updated_at=ts.isoformat().replace("+00:00", "Z"),
        )

    monkeypatch.setattr(makerdao_service, "get_ilk_detail", _fake_get_ilk_detail)

    with _build_client() as client:
        response = client.get("/api/makerdao/ilk", params={"ilk": "ETH-A"})

    assert response.status_code == 200
    assert response.json() == {
        "chain": "ethereum",
        "protocol": "makerdao",
        "ilk": "ETH-A",
        "vault_type": "vault",
        "gem_symbol": "WETH",
        "gem_address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
        "debt_ceiling": "100000000",
        "liquidation_ratio": "1.45",
        "liquidation_penalty": "0.13",
        "stability_fee": None,
        "dust": "5000",
        "updated_at": "2026-04-23T10:00:00Z",
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


@pytest.mark.asyncio
async def test_direct_urn_ilk_scan_uses_user_vault_defaults_by_default(
    monkeypatch,
) -> None:
    def _missing_config():
        raise FileNotFoundError

    monkeypatch.setattr(makerdao_service, "load_config", _missing_config)
    contracts = makerdao_service._MakerDaoContracts(**MAKERDAO_DEFAULT_CONTRACTS)

    ilks = await makerdao_service._load_ilk_names(
        None,
        contracts,
        include_registry=False,
    )

    assert "ETH-A" in ilks
    assert "ALLOCATOR-SPARK-A" not in ilks


@pytest.mark.asyncio
async def test_direct_urn_ilk_scan_honors_explicit_config(monkeypatch) -> None:
    monkeypatch.setattr(
        makerdao_service,
        "load_config",
        lambda: SimpleNamespace(
            makerdao=SimpleNamespace(
                ilk_names=["ETH-A", "ALLOCATOR-SPARK-A", "ETH-A"],
            )
        ),
    )
    contracts = makerdao_service._MakerDaoContracts(**MAKERDAO_DEFAULT_CONTRACTS)

    ilks = await makerdao_service._load_ilk_names(
        None,
        contracts,
        include_registry=False,
    )

    assert ilks == ["ETH-A", "ALLOCATOR-SPARK-A"]


@pytest.mark.asyncio
async def test_get_ilks_returns_cached_rows_without_live_fetch(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    pool = _FakePool(
        _FakeConn(
            ilks=[
                {
                    "ilk": "ETH-A",
                    "vault_type": "vault",
                    "gem_symbol": "WETH",
                    "gem_address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
                    "debt_ceiling": "100000000",
                    "liquidation_ratio": "1.45",
                    "liquidation_penalty": "0.13",
                    "stability_fee": None,
                    "dust": "5000",
                    "updated_at": ts,
                }
            ]
        )
    )

    async def _unexpected_live_fetch(**_kwargs):
        raise AssertionError("live fetch should not run when cache has rows")

    monkeypatch.setattr(makerdao_service, "_fetch_live_ilks", _unexpected_live_fetch)

    result = await makerdao_service.get_ilks(pool, w3="fake-w3")

    assert result.chain == "ethereum"
    assert result.protocol == "makerdao"
    assert len(result.ilks) == 1
    assert result.ilks[0].ilk == "ETH-A"
    assert result.ilks[0].gem_symbol == "WETH"


@pytest.mark.asyncio
async def test_get_ilk_detail_returns_cached_row_without_live_fetch(
    monkeypatch,
) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    pool = _FakePool(
        _FakeConn(
            ilks=[
                {
                    "ilk": "ETH-A",
                    "vault_type": "vault",
                    "gem_symbol": "WETH",
                    "gem_address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
                    "debt_ceiling": "100000000",
                    "liquidation_ratio": "1.45",
                    "liquidation_penalty": "0.13",
                    "stability_fee": None,
                    "dust": "5000",
                    "updated_at": ts,
                }
            ]
        )
    )

    async def _unexpected_live_fetch(*_args, **_kwargs):
        raise AssertionError("live fetch should not run when cache has the ilk")

    monkeypatch.setattr(makerdao_service, "_fetch_live_ilk", _unexpected_live_fetch)

    result = await makerdao_service.get_ilk_detail(pool, ilk="eth-a", w3="fake-w3")

    assert result.ilk == "ETH-A"
    assert result.debt_ceiling == "100000000"
    assert result.liquidation_ratio == "1.45"


@pytest.mark.asyncio
async def test_get_ilk_detail_backfills_when_cache_misses(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    pool = _FakePool(_FakeConn(ilks=[]))
    persisted: list[dict] = []

    async def _fake_fetch_live_ilk(ilk_name, *, w3):
        assert ilk_name == "ETH-A"
        assert w3 == "fake-w3"
        return MakerDaoIlkDetailResponse(
            chain="ethereum",
            protocol="makerdao",
            ilk="ETH-A",
            vault_type="vault",
            gem_symbol="WETH",
            gem_address="0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
            debt_ceiling="100000000",
            liquidation_ratio="1.45",
            liquidation_penalty="0.13",
            stability_fee=None,
            dust="5000",
            updated_at=ts.isoformat().replace("+00:00", "Z"),
        )

    async def _fake_upsert_ilk(_pool, payload):
        persisted.append(payload)

    monkeypatch.setattr(makerdao_service, "_fetch_live_ilk", _fake_fetch_live_ilk)
    monkeypatch.setattr(makerdao_service, "upsert_ilk", _fake_upsert_ilk)

    result = await makerdao_service.get_ilk_detail(pool, ilk="eth-a", w3="fake-w3")

    assert result.ilk == "ETH-A"
    assert persisted[0]["ilk"] == "ETH-A"


@pytest.mark.asyncio
async def test_get_ilks_backfills_live_items_when_cache_is_empty(monkeypatch) -> None:
    contracts = makerdao_service._MakerDaoContracts(**MAKERDAO_DEFAULT_CONTRACTS)
    pool = _FakePool(_FakeConn(ilks=[]))
    persisted: list[dict] = []

    async def _fake_load_ilk_names(w3, loaded_contracts, *, include_registry=True):
        assert w3 == "fake-w3"
        assert loaded_contracts == contracts
        assert include_registry is True
        return ["WBTC-A", "ETH-A"]

    async def _fake_build_live_ilk_item(w3, loaded_contracts, ilk_name, updated_at):
        assert w3 == "fake-w3"
        assert loaded_contracts == contracts
        assert updated_at.tzinfo is not None
        return MakerDaoIlkDetailResponse(
            chain="ethereum",
            protocol="makerdao",
            ilk=ilk_name,
            vault_type="vault",
            gem_symbol=ilk_name.split("-")[0],
            gem_address=None,
            debt_ceiling="0",
            liquidation_ratio="1",
            liquidation_penalty=None,
            stability_fee=None,
            dust="0",
            updated_at=updated_at.isoformat().replace("+00:00", "Z"),
        )

    monkeypatch.setattr(makerdao_service, "_load_contract_addresses", lambda: contracts)
    monkeypatch.setattr(makerdao_service, "_load_ilk_names", _fake_load_ilk_names)
    monkeypatch.setattr(
        makerdao_service,
        "_build_live_ilk_item",
        _fake_build_live_ilk_item,
    )

    async def _fake_upsert_ilk(_pool, payload):
        persisted.append(payload)

    monkeypatch.setattr(
        makerdao_service,
        "upsert_ilk",
        _fake_upsert_ilk,
    )

    result = await makerdao_service.get_ilks(pool, w3="fake-w3")

    assert result.chain == "ethereum"
    assert result.protocol == "makerdao"
    assert [item.ilk for item in result.ilks] == ["ETH-A", "WBTC-A"]
    assert [payload["ilk"] for payload in persisted] == ["ETH-A", "WBTC-A"]


@pytest.mark.asyncio
async def test_build_live_ilk_item_converts_maker_units() -> None:
    contracts = makerdao_service._MakerDaoContracts(**MAKERDAO_DEFAULT_CONTRACTS)
    w3 = _FakeWeb3(
        {
            contracts.vat.lower(): _FakeContract(
                ilks_value=(
                    0,
                    makerdao_service.RAY,
                    0,
                    100_000_000 * makerdao_service.RAD,
                    5_000 * makerdao_service.RAD,
                )
            ),
            contracts.spotter.lower(): _FakeContract(
                ilks_value=(
                    "0x0000000000000000000000000000000000000000",
                    int(Decimal("1.45") * makerdao_service.RAY),
                )
            ),
            contracts.dog.lower(): _FakeContract(
                ilks_value=(
                    "0x0000000000000000000000000000000000000000",
                    int(Decimal("1.13") * makerdao_service.WAD),
                    0,
                    0,
                )
            ),
        }
    )

    item = await makerdao_service._build_live_ilk_item(
        w3,
        contracts,
        "ETH-A",
        datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert item is not None
    assert item.ilk == "ETH-A"
    assert item.gem_symbol == "WETH"
    assert item.debt_ceiling == "100000000"
    assert item.liquidation_ratio == "1.45"
    assert item.liquidation_penalty == "0.13"
    assert item.stability_fee is None
    assert item.dust == "5000"


@pytest.mark.asyncio
async def test_build_live_ilk_item_treats_zero_chop_as_unknown_penalty() -> None:
    contracts = makerdao_service._MakerDaoContracts(**MAKERDAO_DEFAULT_CONTRACTS)
    w3 = _FakeWeb3(
        {
            contracts.vat.lower(): _FakeContract(
                ilks_value=(
                    0,
                    makerdao_service.RAY,
                    0,
                    100_000_000 * makerdao_service.RAD,
                    5_000 * makerdao_service.RAD,
                )
            ),
            contracts.spotter.lower(): _FakeContract(
                ilks_value=(
                    "0x0000000000000000000000000000000000000000",
                    int(Decimal("1.45") * makerdao_service.RAY),
                )
            ),
            contracts.dog.lower(): _FakeContract(
                ilks_value=(
                    "0x0000000000000000000000000000000000000000",
                    0,
                    0,
                    0,
                )
            ),
        }
    )

    item = await makerdao_service._build_live_ilk_item(
        w3,
        contracts,
        "ALLOCATOR-SPARK-A",
        datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert item is not None
    assert item.liquidation_penalty is None
