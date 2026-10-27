"""TypeSafe Jev (System One) HTTP client. Intent and relevance are separate calls."""

from __future__ import annotations

from typing import Any

import httpx

from jplegal.core.config import Settings


class JevClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.http = httpx.AsyncClient(base_url=settings.typesafe_api_base, timeout=settings.jev_timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.s.typesafe_api_key)

    async def close(self) -> None:
        await self.http.aclose()

    async def system_one(self, *, state: Any, questions: dict, model: str | None = None) -> dict:
        if not self.enabled:
            raise RuntimeError("TYPESAFE_API_KEY is not set")
        body = {"model": model or self.s.jev_model, "state": state, "questions": questions}
        r = await self.http.post(
            "/systemone",
            json=body,
            headers={"Authorization": f"Bearer {self.s.typesafe_api_key}", "Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()
