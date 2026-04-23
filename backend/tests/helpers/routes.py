from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient


def build_test_app(
    *,
    router: Any,
    dependency_overrides: Mapping[Any, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    for key, value in (state or {}).items():
        setattr(app.state, key, value)

    for dependency, override in (dependency_overrides or {}).items():
        app.dependency_overrides[dependency] = override

    return app


def build_test_client(
    *,
    router: Any,
    dependency_overrides: Mapping[Any, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> TestClient:
    return TestClient(
        build_test_app(
            router=router,
            dependency_overrides=dependency_overrides,
            state=state,
        )
    )
