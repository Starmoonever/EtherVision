"""Service helpers for JustLend scaffold APIs."""

from __future__ import annotations

from fastapi import HTTPException

from ..constants import JUSTLEND_CHAIN, JUSTLEND_PROTOCOL
from .schemas import JustLendMarketResponse, JustLendScaffoldStatusResponse


def get_scaffold_status() -> JustLendScaffoldStatusResponse:
    return JustLendScaffoldStatusResponse(
        module=JUSTLEND_PROTOCOL,
        status="scaffold",
        chain=JUSTLEND_CHAIN,
        supported_protocols=["trx"],
        message="JustLend backend scaffold is wired into the unified API. Data collection and query logic are pending.",
    )


def get_markets() -> JustLendMarketResponse:
    return JustLendMarketResponse(chain=JUSTLEND_CHAIN, markets=[])


def raise_not_implemented(feature: str) -> None:
    raise HTTPException(
        status_code=501,
        detail=f"JustLend scaffold is ready, but `{feature}` is not implemented yet.",
    )
