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
    MakerDaoPositionListItemResponse,
    MakerDaoPositionsAggregatesResponse,
    MakerDaoPositionsResponse,
    MakerDaoSystemUrnPositionResponse,
    MakerDaoSystemUrnPositionsResponse,
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
    def __init__(self, ilks=None, positions=None, system_positions=None):
        self._ilks = ilks or []
        self._positions = positions or []
        self._system_positions = system_positions or []

    async def fetch(self, sql, *_args):
        if "FROM loan.makerdao_ilks_current" in sql:
            return self._ilks
        if "FROM loan.makerdao_current_vault_positions" in sql:
            return self._positions
        if "FROM loan.makerdao_system_urn_positions_current" in sql:
            return self._system_positions
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


def _build_client(*, ilks=None, positions=None, system_positions=None):
    fake_pool = _FakePool(
        _FakeConn(ilks=ilks, positions=positions, system_positions=system_positions)
    )

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


def test_ilk_route_accepts_collateral_address(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    collateral_address = "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2"

    async def _fake_get_ilk_detail(pool, **kwargs):
        assert pool is not None
        assert kwargs["ilk"] is None
        assert kwargs["address"] == collateral_address
        assert "w3" in kwargs
        return MakerDaoIlkDetailResponse(
            chain="ethereum",
            protocol="makerdao",
            ilk="ETH-A",
            vault_type="vault",
            gem_symbol="WETH",
            gem_address=collateral_address,
            debt_ceiling="100000000",
            liquidation_ratio="1.45",
            liquidation_penalty="0.13",
            stability_fee=None,
            dust="5000",
            updated_at=ts.isoformat().replace("+00:00", "Z"),
        )

    monkeypatch.setattr(makerdao_service, "get_ilk_detail", _fake_get_ilk_detail)

    with _build_client() as client:
        response = client.get(
            "/api/makerdao/ilk", params={"address": collateral_address}
        )

    assert response.status_code == 200
    assert response.json()["ilk"] == "ETH-A"
    assert response.json()["gem_address"] == collateral_address


def test_ilk_route_requires_exactly_one_lookup_param() -> None:
    with _build_client() as client:
        missing_response = client.get("/api/makerdao/ilk")
        duplicate_response = client.get(
            "/api/makerdao/ilk",
            params={
                "ilk": "ETH-A",
                "address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
            },
        )

    assert missing_response.status_code == 400
    assert duplicate_response.status_code == 400


def test_position_route_returns_live_vault_positions(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_get_user_vault_position(pool, **kwargs):
        assert pool is not None
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


def test_system_position_route_returns_system_urn_position(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_get_system_urn_positions(pool, **kwargs):
        assert pool is not None
        assert kwargs["urn"] == "0x691a6c29e9e96dd897718305427ad5d534db16ba"
        assert "w3" in kwargs
        item = MakerDaoSystemUrnPositionResponse(
            chain="ethereum",
            protocol="makerdao",
            position_type="system_urn",
            position_uid=(
                "ethereum:makerdao:system_urn:"
                "0x691a6c29e9e96dd897718305427ad5d534db16ba:ALLOCATOR-SPARK-A"
            ),
            ilk="ALLOCATOR-SPARK-A",
            urn_address="0x691a6c29e9e96dd897718305427Ad5D534db16BA",
            block_number=22334455,
            block_timestamp=ts.isoformat().replace("+00:00", "Z"),
            snapshot_at=ts.isoformat().replace("+00:00", "Z"),
            collateral_symbol="ALLOCATOR-SPARK-A",
            collateral_token_address=None,
            collateral_amount="1000000000000",
            collateral_value_usd="1000000000000",
            debt_symbol="DAI",
            debt_token_address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
            debt_amount="3995880969.538352758976778164",
            debt_value_usd="3995880969.53835276",
            liquidation_ratio="1",
            liquidation_price_usd="0.00399588",
            health_factor="250.257704777309915454",
            is_healthy=True,
            data_source="cache",
        )
        return MakerDaoSystemUrnPositionsResponse(
            chain="ethereum",
            protocol="makerdao",
            urn_address="0x691a6c29e9e96dd897718305427Ad5D534db16BA",
            total_positions=1,
            ilks=["ALLOCATOR-SPARK-A"],
            positions=[item],
        )

    monkeypatch.setattr(
        makerdao_service,
        "get_system_urn_positions",
        _fake_get_system_urn_positions,
    )

    with _build_client() as client:
        response = client.get(
            "/api/makerdao/system/position",
            params={
                "urn": "0x691a6c29e9e96dd897718305427ad5d534db16ba",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_positions"] == 1
    assert payload["ilks"] == ["ALLOCATOR-SPARK-A"]
    assert payload["positions"][0]["position_type"] == "system_urn"
    assert payload["positions"][0]["ilk"] == "ALLOCATOR-SPARK-A"
    assert "vault_id" not in payload["positions"][0]


def test_positions_route_returns_filtered_overview(monkeypatch) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_get_positions(pool, **kwargs):
        assert pool is not None
        assert kwargs == {
            "page": 2,
            "page_size": 10,
            "sort_by": "debt_value_usd",
            "order": "desc",
            "position_scope": "system",
            "ilk": "ALLOCATOR-SPARK-A",
            "is_healthy": True,
            "include_empty": False,
        }
        return MakerDaoPositionsResponse(
            chain="ethereum",
            protocol="makerdao",
            items=[
                MakerDaoPositionListItemResponse(
                    position_uid=(
                        "ethereum:makerdao:system_urn:"
                        "0x691a6c29e9e96dd897718305427ad5d534db16ba:"
                        "ALLOCATOR-SPARK-A"
                    ),
                    position_scope="system",
                    vault_id=None,
                    vault_type="system_urn",
                    ilk="ALLOCATOR-SPARK-A",
                    urn_address="0x691a6c29e9e96dd897718305427Ad5D534db16BA",
                    owner_address=None,
                    proxy_address=None,
                    block_number=22334455,
                    block_timestamp=ts.isoformat().replace("+00:00", "Z"),
                    snapshot_at=ts.isoformat().replace("+00:00", "Z"),
                    collateral_symbol="ALLOCATOR-SPARK-A",
                    collateral_token_address=None,
                    collateral_amount="1000000000000",
                    collateral_value_usd="1000000000000",
                    debt_symbol="DAI",
                    debt_token_address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
                    debt_amount="3995880969.538352758976778164",
                    debt_value_usd="3995880969.53835276",
                    liquidation_ratio="1",
                    liquidation_price_usd="0.00399588",
                    health_factor="250.257704777309915454",
                    is_healthy=True,
                    data_source="cache",
                )
            ],
            page=2,
            page_size=10,
            total=1,
            sort_by="debt_value_usd",
            order="desc",
            position_scope="system",
            include_empty=False,
            aggregates=MakerDaoPositionsAggregatesResponse(
                total_positions=1,
                user_positions=0,
                system_positions=1,
                unhealthy_positions=0,
                total_collateral_value_usd="1000000000000",
                total_debt_value_usd="3995880969.53835276",
                min_health_factor="250.257704777309915454",
                max_health_factor="250.257704777309915454",
            ),
        )

    monkeypatch.setattr(makerdao_service, "get_positions", _fake_get_positions)

    with _build_client() as client:
        response = client.get(
            "/api/makerdao/positions",
            params={
                "page": 2,
                "page_size": 10,
                "sort_by": "debt_value_usd",
                "order": "desc",
                "position_scope": "system",
                "ilk": "ALLOCATOR-SPARK-A",
                "is_healthy": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["position_scope"] == "system"
    assert payload["items"][0]["position_scope"] == "system"
    assert payload["items"][0]["vault_id"] is None
    assert payload["aggregates"]["system_positions"] == 1
    assert payload["aggregates"]["total_debt_value_usd"] == "3995880969.53835276"


@pytest.mark.asyncio
async def test_get_positions_normalizes_filters_and_builds_aggregates(
    monkeypatch,
) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    async def _fake_fetch_current_positions_page(pool, **kwargs):
        assert pool == "pool"
        assert kwargs == {
            "page_size": 25,
            "offset": 25,
            "sort_by": "health_factor",
            "order": "asc",
            "position_scope": "user",
            "ilk": "ETH-A",
            "is_healthy": False,
            "include_empty": False,
        }
        return (
            [
                {
                    "position_uid": "ethereum:makerdao:12345",
                    "position_scope": "user",
                    "vault_id": 12345,
                    "chain": "ethereum",
                    "protocol": "makerdao",
                    "vault_type": "vault",
                    "ilk": "ETH-A",
                    "urn_address": "0x1111111111111111111111111111111111111111",
                    "owner_address": "0x2222222222222222222222222222222222222222",
                    "proxy_address": None,
                    "snapshot_at": ts,
                    "block_timestamp": ts,
                    "block_number": 22334455,
                    "collateral_symbol": "WETH",
                    "collateral_token_address": None,
                    "collateral_amount": Decimal("1.5"),
                    "collateral_value_usd": Decimal("4500"),
                    "debt_symbol": "DAI",
                    "debt_token_address": None,
                    "debt_amount": Decimal("5000"),
                    "debt_value_usd": Decimal("5000"),
                    "liquidation_ratio": Decimal("1.45"),
                    "liquidation_price_usd": Decimal("4833.33333333"),
                    "health_factor": Decimal("0.9"),
                    "is_healthy": False,
                }
            ],
            {
                "total_count": 3,
                "user_positions": 3,
                "system_positions": 0,
                "unhealthy_positions": 1,
                "total_collateral_value_usd": Decimal("12000"),
                "total_debt_value_usd": Decimal("9000"),
                "min_health_factor": Decimal("0.9"),
                "max_health_factor": Decimal("2.1"),
            },
        )

    monkeypatch.setattr(
        makerdao_service,
        "fetch_current_positions_page",
        _fake_fetch_current_positions_page,
    )

    result = await makerdao_service.get_positions(
        "pool",
        page=2,
        page_size=25,
        sort_by="health_factor",
        order="asc",
        position_scope="user",
        ilk="eth-a",
        is_healthy=False,
    )

    assert result.total == 3
    assert result.items[0].position_uid == "ethereum:makerdao:12345"
    assert result.items[0].is_healthy is False
    assert result.aggregates.unhealthy_positions == 1
    assert result.aggregates.total_collateral_value_usd == "12000"


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
async def test_live_position_falls_back_to_direct_urn_when_cdp_refs_are_empty(
    monkeypatch,
) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    urn = "0x1111111111111111111111111111111111111111"
    direct_ref = {
        "vault_id": None,
        "owner_address": None,
        "proxy_address": None,
        "urn_address": urn,
        "ilk": "ETH-A",
    }
    calls: list[str] = []

    class _EthWithBlock:
        async def get_block(self, _tag):
            return {"number": 22334455, "timestamp": int(ts.timestamp())}

    async def _fake_resolve_cdp_refs(_w3, _contracts, address):
        assert address == urn
        calls.append("cdp")
        return []

    async def _fake_resolve_direct_urn_refs(_w3, _contracts, address):
        assert address == urn
        calls.append("urn")
        return [direct_ref]

    async def _fake_build_live_position_item(
        _w3,
        _contracts,
        ref,
        *,
        block_number,
        block_timestamp,
        snapshot_at,
    ):
        assert ref == direct_ref
        assert block_number == 22334455
        assert block_timestamp == ts
        assert snapshot_at.tzinfo is not None
        return MakerDaoVaultPositionItemResponse(
            vault_uid=f"ethereum:makerdao:urn:{urn}:ETH-A",
            vault_id=None,
            vault_type="vault",
            ilk="ETH-A",
            urn_address=urn,
            owner_address=None,
            proxy_address=None,
            block_number=block_number,
            block_timestamp=ts.isoformat().replace("+00:00", "Z"),
            snapshot_at=snapshot_at.isoformat().replace("+00:00", "Z"),
            collateral_symbol="WETH",
            collateral_token_address="0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
            collateral_amount="1",
            collateral_value_usd="3000",
            debt_symbol="DAI",
            debt_token_address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
            debt_amount="1000",
            debt_value_usd="1000",
            liquidation_ratio="1.45",
            liquidation_price_usd="1450",
            health_factor="2.06896551724137931",
            is_healthy=True,
            data_source="onchain-live",
            assets=[],
        )

    monkeypatch.setattr(makerdao_service, "_resolve_cdp_refs", _fake_resolve_cdp_refs)
    monkeypatch.setattr(
        makerdao_service,
        "_resolve_direct_urn_refs",
        _fake_resolve_direct_urn_refs,
    )
    monkeypatch.setattr(
        makerdao_service,
        "_build_live_position_item",
        _fake_build_live_position_item,
    )

    items = await makerdao_service._fetch_live_vault_positions(
        urn,
        w3=SimpleNamespace(eth=_EthWithBlock()),
        vault_id=None,
        ilk=None,
        include_empty=False,
    )

    assert calls == ["cdp", "urn"]
    assert items[0].vault_uid == f"ethereum:makerdao:urn:{urn}:ETH-A"


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
async def test_get_ilk_detail_returns_cached_row_by_address_without_live_fetch(
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
        raise AssertionError("live fetch should not run when cache has the address")

    monkeypatch.setattr(
        makerdao_service,
        "_fetch_live_ilk_by_address",
        _unexpected_live_fetch,
    )

    result = await makerdao_service.get_ilk_detail(
        pool,
        address="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        w3="fake-w3",
    )

    assert result.ilk == "ETH-A"
    assert result.gem_symbol == "WETH"


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
async def test_get_ilk_detail_backfills_by_address_when_cache_misses(
    monkeypatch,
) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    collateral_address = "0x514910771AF9Ca656af840dff83E8264EcF986CA"
    pool = _FakePool(_FakeConn(ilks=[]))
    persisted: list[dict] = []

    async def _fake_fetch_live_ilk_by_address(token_address, *, w3):
        assert token_address == collateral_address.lower()
        assert w3 == "fake-w3"
        return MakerDaoIlkDetailResponse(
            chain="ethereum",
            protocol="makerdao",
            ilk="LINK-A",
            vault_type="vault",
            gem_symbol="LINK",
            gem_address=collateral_address,
            debt_ceiling="5000000",
            liquidation_ratio="1.65",
            liquidation_penalty="0.13",
            stability_fee=None,
            dust="5000",
            updated_at=ts.isoformat().replace("+00:00", "Z"),
        )

    async def _fake_upsert_ilk(_pool, payload):
        persisted.append(payload)

    monkeypatch.setattr(
        makerdao_service,
        "_fetch_live_ilk_by_address",
        _fake_fetch_live_ilk_by_address,
    )
    monkeypatch.setattr(makerdao_service, "upsert_ilk", _fake_upsert_ilk)

    result = await makerdao_service.get_ilk_detail(
        pool,
        address=collateral_address,
        w3="fake-w3",
    )

    assert result.ilk == "LINK-A"
    assert persisted[0]["gem_address"] == collateral_address


@pytest.mark.asyncio
async def test_get_user_position_dedupes_cached_cdp_and_direct_urn_rows(
    monkeypatch,
) -> None:
    urn = "0xf12eEAa52438f0ebf170EC258DDB34c70088a863"
    older = datetime(2026, 4, 27, 3, 29, 45, tzinfo=timezone.utc)
    newer = datetime(2026, 4, 27, 6, 41, 46, tzinfo=timezone.utc)
    base_row = {
        "chain": "ethereum",
        "protocol": "makerdao",
        "vault_type": "vault",
        "ilk": "ETH-C",
        "urn_address": urn,
        "owner_address": None,
        "proxy_address": None,
        "block_timestamp": older,
        "block_number": 24968691,
        "collateral_symbol": "WETH",
        "collateral_token_address": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
        "collateral_amount": "186.005196786302072154",
        "collateral_value_usd": "442447.24429985",
        "debt_symbol": "DAI",
        "debt_token_address": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "debt_amount": "213350.284330491339771128",
        "debt_value_usd": "213350.28433049",
        "liquidation_ratio": "1.7",
        "liquidation_price_usd": "1949.92123676",
        "health_factor": "1.219886280906473689",
        "is_healthy": True,
    }
    direct_urn_row = {
        **base_row,
        "vault_uid": f"ethereum:makerdao:urn:{urn.lower()}:ETH-C",
        "vault_id": None,
        "snapshot_at": older,
    }
    cdp_row = {
        **base_row,
        "vault_uid": "ethereum:makerdao:31602",
        "vault_id": 31602,
        "snapshot_at": newer,
        "block_timestamp": newer,
    }
    pool = _FakePool(_FakeConn(positions=[cdp_row, direct_urn_row]))

    async def _unexpected_live_fetch(*_args, **_kwargs):
        raise AssertionError("live fetch should not run when cache has rows")

    monkeypatch.setattr(
        makerdao_service,
        "_fetch_live_vault_positions",
        _unexpected_live_fetch,
    )

    result = await makerdao_service.get_user_vault_position(
        pool,
        address="0xF12EEAA52438F0EBF170EC258DDB34C70088A863",
        include_empty=True,
    )

    assert result.total_positions == 1
    assert result.positions[0].vault_uid == "ethereum:makerdao:31602"
    assert result.positions[0].vault_id == 31602


@pytest.mark.asyncio
async def test_get_system_urn_positions_returns_all_cached_ilks_without_live_fetch(
    monkeypatch,
) -> None:
    urn = "0x691a6c29e9e96dd897718305427Ad5D534db16BA"
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    base_row = {
        "chain": "ethereum",
        "protocol": "makerdao",
        "position_type": "system_urn",
        "urn_address": urn,
        "snapshot_at": ts,
        "block_timestamp": ts,
        "block_number": 22334455,
        "collateral_symbol": "ALLOCATOR-SPARK-A",
        "collateral_token_address": None,
        "collateral_amount": "1000000000000",
        "collateral_value_usd": "1000000000000",
        "debt_symbol": "DAI",
        "debt_token_address": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "debt_amount": "3995880969.538352758976778164",
        "debt_value_usd": "3995880969.53835276",
        "liquidation_ratio": "1",
        "liquidation_price_usd": "0.00399588",
        "health_factor": "250.257704777309915454",
        "is_healthy": True,
    }
    pool = _FakePool(
        _FakeConn(
            system_positions=[
                {
                    **base_row,
                    "position_uid": (
                        f"ethereum:makerdao:system_urn:{urn.lower()}:ALLOCATOR-SPARK-A"
                    ),
                    "ilk": "ALLOCATOR-SPARK-A",
                },
                {
                    **base_row,
                    "position_uid": (
                        f"ethereum:makerdao:system_urn:{urn.lower()}:ALLOCATOR-BLOOM-A"
                    ),
                    "ilk": "ALLOCATOR-BLOOM-A",
                    "collateral_symbol": "ALLOCATOR-BLOOM-A",
                },
            ]
        )
    )

    async def _unexpected_live_fetch(*_args, **_kwargs):
        raise AssertionError("live fetch should not run when cache has rows")

    monkeypatch.setattr(
        makerdao_service,
        "_fetch_live_system_urn_positions",
        _unexpected_live_fetch,
    )

    result = await makerdao_service.get_system_urn_positions(
        pool,
        urn=urn.lower(),
        w3="fake-w3",
    )

    assert result.total_positions == 2
    assert result.ilks == ["ALLOCATOR-SPARK-A", "ALLOCATOR-BLOOM-A"]
    assert [position.ilk for position in result.positions] == result.ilks


@pytest.mark.asyncio
async def test_get_user_position_backfills_missing_ilk_before_position(
    monkeypatch,
) -> None:
    ts = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)
    pool = _FakePool(_FakeConn(ilks=[], positions=[]))
    events: list[tuple[str, str]] = []

    live_position = MakerDaoVaultPositionItemResponse(
        vault_uid="ethereum:makerdao:12345",
        vault_id=12345,
        vault_type="vault",
        ilk="LINK-A",
        urn_address="0x1111111111111111111111111111111111111111",
        owner_address="0x2222222222222222222222222222222222222222",
        proxy_address=None,
        block_number=22334455,
        block_timestamp=ts.isoformat().replace("+00:00", "Z"),
        snapshot_at=ts.isoformat().replace("+00:00", "Z"),
        collateral_symbol="LINK",
        collateral_token_address="0x514910771AF9Ca656af840dff83E8264EcF986CA",
        collateral_amount="100",
        collateral_value_usd="1500",
        debt_symbol="DAI",
        debt_token_address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
        debt_amount="500",
        debt_value_usd="500",
        liquidation_ratio="1.65",
        liquidation_price_usd="8.25",
        health_factor="1.818181818181818182",
        is_healthy=True,
        data_source="onchain-live",
        assets=[],
    )

    async def _fake_fetch_live_vault_positions(*_args, **_kwargs):
        return [live_position]

    async def _fake_fetch_live_ilk(ilk_name, *, w3):
        assert ilk_name == "LINK-A"
        assert w3 == "fake-w3"
        return None

    async def _fake_upsert_ilk(_pool, payload):
        events.append(("ilk", payload["ilk"]))

    async def _fake_upsert_current_vault_position(_pool, payload):
        events.append(("position", payload["ilk"]))

    monkeypatch.setattr(
        makerdao_service,
        "_fetch_live_vault_positions",
        _fake_fetch_live_vault_positions,
    )
    monkeypatch.setattr(makerdao_service, "_fetch_live_ilk", _fake_fetch_live_ilk)
    monkeypatch.setattr(makerdao_service, "upsert_ilk", _fake_upsert_ilk)
    monkeypatch.setattr(
        makerdao_service,
        "upsert_current_vault_position",
        _fake_upsert_current_vault_position,
    )

    result = await makerdao_service.get_user_vault_position(
        pool,
        address="0x2222222222222222222222222222222222222222",
        w3="fake-w3",
    )

    assert result.positions[0].ilk == "LINK-A"
    assert events == [("ilk", "LINK-A"), ("position", "LINK-A")]


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
