from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from web3 import AsyncWeb3

from compound_crawler import crawler
from compound_crawler.config import AppConfig


class _FakeEth:
    def __init__(self, code: bytes):
        self._code = code
        self.calls: list[tuple[str, int | None]] = []

    async def get_code(self, address, block_identifier=None):
        self.calls.append((str(address), block_identifier))
        return self._code


class _FakeW3:
    def __init__(self, code: bytes):
        self.eth = _FakeEth(code)


@pytest.mark.asyncio
async def test_collect_v3_markets_skips_undeployed_market() -> None:
    cfg = cast(
        AppConfig,
        SimpleNamespace(crawler=SimpleNamespace(concurrency=2), protocol="v3"),
    )
    w3 = cast(AsyncWeb3, _FakeW3(b""))
    point_ts = datetime(2022, 8, 28, 11, 0, 0, tzinfo=timezone.utc)
    deployment_cache: dict[str, dict[str, int]] = {}

    with patch.object(
        crawler, "_collect_v3_market_at_block", new=AsyncMock()
    ) as collect:
        (
            market_rows,
            reserve_rows,
            config_rows,
            config_asset_rows,
            status_rows,
        ) = await crawler._collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427392,
            markets=["0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840"],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )

    assert market_rows == []
    assert reserve_rows == []
    assert config_rows == []
    assert config_asset_rows == []
    assert status_rows == []
    assert collect.await_count == 0
    assert len(cast(_FakeW3, w3).eth.calls) == 1
    assert (
        deployment_cache["0x3afdc9bca9213a35503b077a6072f3d0d5ab0840"][
            "missing_through"
        ]
        == 15427392
    )


@pytest.mark.asyncio
async def test_collect_v3_markets_reuses_missing_code_cache() -> None:
    cfg = cast(
        AppConfig,
        SimpleNamespace(crawler=SimpleNamespace(concurrency=2), protocol="v3"),
    )
    w3 = cast(AsyncWeb3, _FakeW3(b""))
    point_ts = datetime(2022, 8, 28, 11, 0, 0, tzinfo=timezone.utc)
    deployment_cache: dict[str, dict[str, int]] = {}
    market = "0x5D409e56D886231aDAf00c8775665AD0f9897b56"

    with patch.object(
        crawler, "_collect_v3_market_at_block", new=AsyncMock()
    ) as collect:
        await crawler._collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427392,
            markets=[market],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )
        await crawler._collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427300,
            markets=[market],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )

    assert collect.await_count == 0
    assert len(cast(_FakeW3, w3).eth.calls) == 1


def test_governance_config_hash_is_stable() -> None:
    payload = {
        "base_token": "0x1",
        "asset_configs": [{"asset": "0x2", "supply_cap": "100"}],
        "target_reserves": "5",
    }
    assert crawler._governance_config_hash(payload) == crawler._governance_config_hash(
        {
            "target_reserves": "5",
            "asset_configs": [{"supply_cap": "100", "asset": "0x2"}],
            "base_token": "0x1",
        }
    )


def test_annualize_factor_from_per_second_rate() -> None:
    assert crawler._annualize_factor(10**18) == crawler.SECONDS_PER_YEAR
