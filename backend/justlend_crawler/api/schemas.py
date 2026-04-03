"""Pydantic schemas for JustLend scaffold APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JustLendScaffoldStatusResponse(BaseModel):
    module: str = Field(description="模块名。")
    status: str = Field(description="当前实现状态。")
    chain: str = Field(description="目标链。")
    supported_protocols: list[str] = Field(description="当前保留的协议标识。")
    message: str = Field(description="当前骨架说明。")


class JustLendMarketResponse(BaseModel):
    chain: str = Field(description="目标链。")
    markets: list[str] = Field(description="当前预留的市场列表。")
