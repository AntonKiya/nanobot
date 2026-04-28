"""Aviasales (Travelpayouts) Data API HTTP client.

Thin httpx wrapper. Sends `X-Access-Token` and returns raw JSON dicts.
The tools/normalize layers shape the response for the agent.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

_BASE = "https://api.travelpayouts.com"
_TIMEOUT = 15.0


class AviasalesAPIError(Exception):
    """Travelpayouts API returned a non-2xx response."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class AviasalesClient:
    """Async client for Travelpayouts Aviasales Data API endpoints."""

    def __init__(self, api_token: str, market: str = "ru") -> None:
        self._token = api_token
        self._market = market

    def _headers(self) -> dict[str, str]:
        return {
            "X-Access-Token": self._token,
            "Accept-Encoding": "gzip, deflate",
        }

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        clean.setdefault("market", self._market)
        url = f"{_BASE}{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            try:
                resp = await http.get(url, params=clean, headers=self._headers())
            except httpx.HTTPError as e:
                logger.warning("aviasales request failed: {}", e)
                raise AviasalesAPIError(0, f"network error: {e}") from e
        if resp.status_code >= 400:
            raise AviasalesAPIError(resp.status_code, resp.text[:300])
        try:
            return resp.json()
        except ValueError as e:
            raise AviasalesAPIError(resp.status_code, f"invalid JSON: {e}") from e

    # --- Endpoints --------------------------------------------------------

    async def prices_for_dates(self, **params: Any) -> dict[str, Any]:
        return await self._get("/aviasales/v3/prices_for_dates", params)

    async def grouped_prices(self, **params: Any) -> dict[str, Any]:
        return await self._get("/aviasales/v3/grouped_prices", params)

    async def week_matrix(self, **params: Any) -> dict[str, Any]:
        return await self._get("/v2/prices/week-matrix", params)

    async def search_by_price_range(self, **params: Any) -> dict[str, Any]:
        return await self._get("/aviasales/v3/search_by_price_range", params)

    async def gather(self, *coros: Any) -> list[Any]:
        """Run several endpoint coroutines in parallel; returns results or exceptions."""
        return await asyncio.gather(*coros, return_exceptions=True)
