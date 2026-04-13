from __future__ import annotations

from typing import Any

import pytest

from morpho_crawler.api.service import get_user_position


class _Call:
    def __init__(self, value):
        self._value = value

    async def call(self, block_identifier=None):
        return self._value


class _Functions:
    def __init__(self, mapping):
        self._mapping = mapping

    def __getattr__(self, name):
        def _norm(value: Any):
            if isinstance(value, str) and value.startswith("0x"):
                return value.lower()
            if isinstance(value, tuple):
                return tuple(_norm(item) for item in value)
            return value

        def _fn(*args):
            return _Call(self._mapping[name][_norm(args)])

        return _fn


class _Contract:
    def __init__(self, mapping):
        self.functions = _Functions(mapping)


class _Eth:
    def __init__(self, contracts):
        self._contracts = contracts

    def contract(self, address, abi):
        return self._contracts[address.lower()]

    async def get_block(self, block_identifier):
        return {"number": 123, "timestamp": 1_712_531_200}


class _FakeW3:
    def __init__(self, contracts):
        self.eth = _Eth(contracts)


@pytest.mark.asyncio
async def test_get_user_position_realtime_calculates_fields():
    market_id = "0x" + "11" * 32
    user = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    morpho = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
    loan = "0x1111111111111111111111111111111111111111"
    collateral = "0x2222222222222222222222222222222222222222"
    oracle = "0x3333333333333333333333333333333333333333"
    irm = "0x4444444444444444444444444444444444444444"

    contracts = {
        morpho: _Contract(
            {
                "idToMarketParams": {
                    (bytes.fromhex("11" * 32),): (
                        loan,
                        collateral,
                        oracle,
                        irm,
                        8 * 10**17,
                    )
                },
                "market": {
                    (bytes.fromhex("11" * 32),): (
                        2_000_000,
                        2_000_000,
                        1_000_000,
                        1_000_000,
                        1_712_531_140,
                        0,
                    )
                },
                "position": {
                    (bytes.fromhex("11" * 32), user.lower()): (
                        500_000,
                        250_000,
                        2 * 10**18,
                    )
                },
            }
        ),
        loan: _Contract({"decimals": {(): 6}, "symbol": {(): "USDC"}}),
        collateral: _Contract({"decimals": {(): 18}, "symbol": {(): "wstETH"}}),
        oracle: _Contract({"price": {(): 1_500_000_000_000_000_000_000_000}}),
        irm: _Contract(
            {
                "borrowRateView": {
                    (
                        (
                            loan.lower(),
                            collateral.lower(),
                            oracle.lower(),
                            irm.lower(),
                            8 * 10**17,
                        ),
                        (
                            2_000_000,
                            2_000_000,
                            1_000_000,
                            1_000_000,
                            1_712_531_140,
                            0,
                        ),
                    ): 0
                }
            }
        ),
    }

    response = await get_user_position(
        _FakeW3(contracts),
        address=user,
        market_id=market_id,
        protocol="blue",
    )

    assert response.market_id == market_id
    assert response.loan_token_symbol == "USDC"
    assert response.collateral_token_symbol == "wstETH"
    assert response.supply_assets == "0.333333"
    assert response.borrow_assets == "0.125001"
    assert response.collateral_assets == "2"
    assert response.collateral_value_in_loan_asset == "3"
    assert response.max_borrowable_in_loan_asset == "2.4"
    assert response.health_factor == "19.199846401228790170"
    assert response.price_quote == "1.5"
    assert response.is_healthy is True
