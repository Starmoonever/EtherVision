from __future__ import annotations

from scripts.justlend import repair_current_collateral_sides as repair_script


def test_effective_collateral_flag_prefers_entered() -> None:
    assert (
        repair_script._effective_collateral_flag(
            {"entered": True, "is_collateral": False}
        )
        is True
    )
    assert (
        repair_script._effective_collateral_flag(
            {"entered": False, "is_collateral": True}
        )
        is False
    )


def test_effective_collateral_flag_falls_back_to_is_collateral() -> None:
    assert repair_script._effective_collateral_flag({"is_collateral": True}) is True
    assert repair_script._effective_collateral_flag({"is_collateral": False}) is False
    assert repair_script._effective_collateral_flag({}) is None


def test_normalized_asset_side_repairs_legacy_rows() -> None:
    assert (
        repair_script._normalized_asset_side("collateral", {"entered": False})
        == "supply"
    )
    assert (
        repair_script._normalized_asset_side("supply", {"is_collateral": True})
        == "collateral"
    )
    assert (
        repair_script._normalized_asset_side("collateral", {"is_collateral": True})
        == "collateral"
    )
    assert (
        repair_script._normalized_asset_side("borrow", {"entered": False}) == "borrow"
    )
