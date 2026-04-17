from __future__ import annotations

from justlend_crawler import rpc as justlend_rpc
from justlend_crawler.current_position_backfill import (
    build_target_address_symbol_map,
    collect_history_user_matches,
    merge_user_addresses,
    normalize_user_address_bytes,
    normalize_user_addresses,
)


def test_build_target_address_symbol_map_includes_market_and_underlying_addresses() -> (
    None
):
    market_trx = justlend_rpc._hex_to_tron_base58(
        "411111111111111111111111111111111111111111"
    )
    market_usdt = justlend_rpc._hex_to_tron_base58(
        "412222222222222222222222222222222222222222"
    )
    underlying_usdt = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    rows = [
        {
            "market_address": market_trx,
            "underlying_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
            "underlying_symbol": "TRX",
        },
        {
            "market_address": market_usdt,
            "underlying_address": underlying_usdt,
            "underlying_symbol": "USDT",
        },
        {
            "market_address": justlend_rpc._hex_to_tron_base58(
                "413333333333333333333333333333333333333333"
            ),
            "underlying_address": justlend_rpc._hex_to_tron_base58(
                "414444444444444444444444444444444444444444"
            ),
            "underlying_symbol": "JST",
        },
    ]

    result = build_target_address_symbol_map(rows, target_symbols={"TRX", "USDT"})

    assert result[market_trx] == "TRX"
    assert result["T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"] == "TRX"
    assert result[market_usdt] == "USDT"
    assert result[underlying_usdt] == "USDT"
    assert "JST" not in result.values()


def test_collect_history_user_matches_requires_all_symbols() -> None:
    market_trx = justlend_rpc._hex_to_tron_base58(
        "411111111111111111111111111111111111111111"
    )
    market_usdt = justlend_rpc._hex_to_tron_base58(
        "412222222222222222222222222222222222222222"
    )
    user_a = bytes.fromhex("41aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    user_b = bytes.fromhex("41bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    address_to_symbol = {
        market_trx: "TRX",
        market_usdt: "USDT",
        "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb": "TRX",
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": "USDT",
    }
    rows = [
        {
            "user_address": user_a,
            "contract": f'{{"contract_address":"{market_usdt}"}}',
            "parse_input": None,
        },
        {
            "user_address": user_a,
            "contract": None,
            "parse_input": '{"asset":"T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"}',
        },
        {
            "user_address": user_b,
            "contract": f'{{"contract_address":"{market_usdt}"}}',
            "parse_input": None,
        },
    ]

    result = collect_history_user_matches(
        rows,
        address_to_symbol=address_to_symbol,
        target_symbols={"TRX", "USDT"},
        match_mode="all",
    )

    assert result == [user_a]


def test_collect_history_user_matches_supports_any_mode() -> None:
    market_usdt = justlend_rpc._hex_to_tron_base58(
        "412222222222222222222222222222222222222222"
    )
    user_a = bytes.fromhex("41aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    user_b = bytes.fromhex("41bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    rows = [
        {
            "user_address": user_a,
            "contract": f'{{"contract_address":"{market_usdt}"}}',
            "parse_input": None,
        },
        {
            "user_address": user_b,
            "contract": None,
            "parse_input": '{"asset":"T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"}',
        },
    ]

    result = collect_history_user_matches(
        rows,
        address_to_symbol={
            market_usdt: "USDT",
            "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb": "TRX",
        },
        target_symbols={"TRX", "USDT"},
        match_mode="any",
    )

    assert result == [user_a, user_b]


def test_merge_user_addresses_preserves_order_and_deduplicates() -> None:
    user_a = bytes.fromhex("41aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    user_b = bytes.fromhex("41bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    user_c = bytes.fromhex("41cccccccccccccccccccccccccccccccccccccccc")

    result = merge_user_addresses([user_a, user_b], [user_b, user_c], [user_a])

    assert result == [user_a, user_b, user_c]


def test_normalize_user_address_bytes_converts_legacy_base58_bytea() -> None:
    legacy = b"TKVnVyJiTzyCDgTkZRYc5LM4q8B7xXEbh5"

    result = normalize_user_address_bytes(legacy)

    assert result.hex() == "41688192f462772678af365af6357cc4738e1da2e7"


def test_normalize_user_addresses_tracks_legacy_aliases() -> None:
    canonical = bytes.fromhex("41688192f462772678af365af6357cc4738e1da2e7")
    legacy = b"TKVnVyJiTzyCDgTkZRYc5LM4q8B7xXEbh5"

    users, aliases = normalize_user_addresses([legacy, canonical])

    assert users == [canonical]
    assert aliases == {canonical: [legacy]}
