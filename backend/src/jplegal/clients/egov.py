"""e-Gov 法令API v2 + XML一括ダウンロード client, with a system-wide rate limit.

Principles (e-Gov publishes no rate limit → self-imposed):
  * At most 1 request / EGOV_MIN_INTERVAL_SEC (default 1s) for ALL workers – locked on Redis.
  * Exponential-backoff retry + jitter for 429 / 5xx / timeout, honoring Retry-After.
  * Cache raw files by revision_id → never re-download a revision already fetched.
  * Bulk ingest → use bulk download instead of per-law API calls.
Data: 公共データ利用規約 (PDL1.0) – must credit the source 「出典：e-Gov法令検索」.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from redis.asyncio import Redis

from jplegal.core.config import Settings
from jplegal.core.models import LawMeta

log = logging.getLogger(__name__)


class RedisRateLimiter:
    """Enforce a minimum gap between 2 requests, shared across all processes (SET NX PX)."""

    def __init__(self, redis: Redis | None, key: str, min_interval: float):
        self.redis = redis
        self.key = key
        self.min_interval_ms = int(min_interval * 1000)
        self._local_lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        if self.redis is None:  # single-process fallback (CLI / test)
            async with self._local_lock:
                wait = self._last + self.min_interval_ms / 1000 - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
            return
        while True:
            if await self.redis.set(self.key, "1", nx=True, px=self.min_interval_ms):
                return
            ttl = await self.redis.pttl(self.key)
            await asyncio.sleep(max(ttl, 50) / 1000)


@dataclass
class EgovLaw:
    meta: LawMeta
    xml: bytes
    revision_info: dict


class EgovClient:
    def __init__(self, settings: Settings, redis: Redis | None = None):
        self.s = settings
        self.limiter = RedisRateLimiter(redis, "ratelimit:egov", settings.egov_min_interval_sec)
        self.http = httpx.AsyncClient(
            timeout=settings.egov_timeout,
            headers={"User-Agent": settings.egov_user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, url: str, params: dict | None = None, *, stream_to: Path | None = None) -> httpx.Response | Path:
        attempt = 0
        while True:
            await self.limiter.acquire()
            try:
                if stream_to is not None:
                    async with self.http.stream("GET", url, params=params) as r:
                        if r.status_code == 200:
                            tmp = stream_to.with_suffix(stream_to.suffix + ".part")
                            tmp.parent.mkdir(parents=True, exist_ok=True)
                            with tmp.open("wb") as f:
                                async for chunk in r.aiter_bytes(1 << 20):
                                    f.write(chunk)
                            tmp.replace(stream_to)
                            return stream_to
                        status, retry_after = r.status_code, r.headers.get("Retry-After")
                        await r.aread()
                        resp = r
                else:
                    resp = await self.http.get(url, params=params)
                    if resp.status_code == 200:
                        return resp
                    status, retry_after = resp.status_code, resp.headers.get("Retry-After")
                if status not in (429, 500, 502, 503, 504) or attempt >= self.s.egov_max_retries:
                    resp.raise_for_status()
                    return resp
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt >= self.s.egov_max_retries:
                    raise
                log.warning("e-Gov transport error %s (attempt %d)", e, attempt + 1)
                retry_after = None
            delay = float(retry_after) if retry_after and str(retry_after).isdigit() else 2 ** attempt
            delay = min(delay, 120) + random.uniform(0, 1)
            log.warning("e-Gov retry in %.1fs (attempt %d) url=%s", delay, attempt + 1, url)
            await asyncio.sleep(delay)
            attempt += 1

    # ---------------- API v2 ----------------
    async def search_laws(self, title: str, limit: int = 20) -> list[dict]:
        r = await self._get(f"{self.s.egov_api_base}/laws", {"law_title": title, "limit": limit})
        return r.json().get("laws", [])  # type: ignore[union-attr]

    async def get_law(self, law_id: str, cache_dir: Path | None = None) -> EgovLaw:
        """Any of law_id / law_num / law_revision_id works."""
        r = await self._get(f"{self.s.egov_api_base}/law_data/{law_id}", {"law_full_text_format": "xml"})
        data = r.json()  # type: ignore[union-attr]
        info, rev = data.get("law_info", {}), data.get("revision_info", {})
        xml = base64.b64decode(data["law_full_text"])
        meta = LawMeta(
            law_id=info.get("law_id", law_id),
            title=rev.get("law_title", ""),
            law_num=info.get("law_num", ""),
            abbrev=(rev.get("abbrev") or "").split(",")[0],
            law_type=rev.get("law_type") or info.get("law_type", ""),
            category=rev.get("category") or "",
            revision_id=rev.get("law_revision_id", ""),
            promulgation_date=info.get("promulgation_date", ""),
            enforcement_date=rev.get("amendment_enforcement_date") or "",
            source="egov",
        )
        if cache_dir is not None:
            d = cache_dir / "egov" / meta.law_id
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{meta.revision_id or 'current'}.xml").write_bytes(xml)
        return EgovLaw(meta=meta, xml=xml, revision_info=rev)

    # ---------------- Bulk download ----------------
    async def download_bulk(self, dest: Path, *, category_cd: int | None = None,
                            update_date: str | None = None) -> Path:
        """file_section=1: all; 2: by category_cd; 3: laws updated on a date (YYYYMMDD, ≤3 months)."""
        if update_date:
            params = {"file_section": 3, "update_date": update_date, "only_xml_flag": "true"}
        elif category_cd is not None:
            params = {"file_section": 2, "category_cd": category_cd, "only_xml_flag": "true"}
        else:
            params = {"file_section": 1, "only_xml_flag": "true"}
        out = await self._get(self.s.egov_bulk_url, params, stream_to=dest)
        return out  # type: ignore[return-value]
