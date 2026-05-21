import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import httpx

_CONFIDENCE_ORDER: dict[str, int] = {"confirmed": 0, "likely": 1, "possible": 2}

_MAX_RETRIES = 4
_RETRY_BASE = 2.0


@dataclass
class LinkedAccount:
    system: str
    identifier: str
    confidence: Literal["confirmed", "likely", "possible"]
    match_reason: str
    profile_url: str | None = None


async def get_with_backoff(
    client: httpx.AsyncClient,
    url: str,
    **kwargs,
) -> httpx.Response:
    """GET with exponential backoff + jitter on 429 and 5xx."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, **kwargs)
        except httpx.RequestError as exc:
            last_exc = exc
            await asyncio.sleep(_RETRY_BASE ** attempt + random.random())
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == _MAX_RETRIES - 1:
                resp.raise_for_status()
            await asyncio.sleep(_RETRY_BASE ** attempt + random.random())
            continue
        resp.raise_for_status()
        return resp
    if last_exc:
        raise last_exc
    raise RuntimeError(f"GET {url} failed after {_MAX_RETRIES} attempts")  # pragma: no cover


class LinkedAccountsProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    async def fetch_all(self) -> None:
        """Bulk-fetch and cache this provider's data. Called once per refresh cycle."""

    @abstractmethod
    async def match(
        self,
        member: dict,
        known_identifiers: set[str],
    ) -> list[LinkedAccount]:
        """
        Return linked accounts for one PocketID member dict.
        known_identifiers contains identifiers already found by earlier providers
        so each provider can extend the search surface (e.g. Mattermost can also
        match on org emails found by Migadu) and avoid returning duplicates.
        """
