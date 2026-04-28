"""Aviasales flight-search tools for the nanobot agent."""

from __future__ import annotations

import json
import re
from typing import Any

from nanobot.agent.tools.aviasales.client import AviasalesAPIError, AviasalesClient
from nanobot.agent.tools.aviasales.normalize import (
    normalize_list,
    normalize_week_matrix,
)
from nanobot.agent.tools.aviasales.resolver import ResolverError, resolve_city
from nanobot.agent.tools.base import Tool

_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(msg: str) -> str:
    return f"Error: {msg}"


def _api_error(e: AviasalesAPIError) -> str:
    return _err(f"Aviasales API ({e.status}): {e}")


def _validate_date(value: str | None, field: str, *, allow_empty: bool = True) -> str | None:
    if value is None or value == "":
        if allow_empty:
            return None
        return f"{field} обязателен"
    if not _DATE_RE.match(value):
        return f"{field} должен быть в формате YYYY-MM или YYYY-MM-DD, получено {value!r}"
    return None


def _resolve(query: str) -> tuple[str | None, str | None]:
    """Returns (iata, error_message). One is always None."""
    try:
        return resolve_city(query).iata, None
    except ResolverError as e:
        return None, str(e)


class _AviasalesBaseTool(Tool):
    def __init__(self, client: AviasalesClient) -> None:
        self._client = client

    @property
    def read_only(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# aviasales_search_dates
# ---------------------------------------------------------------------------

class AviasalesSearchDatesTool(_AviasalesBaseTool):
    """Main flight-price search by route and dates."""

    @property
    def name(self) -> str:
        return "aviasales_search_dates"

    @property
    def description(self) -> str:
        return (
            "Search Aviasales cached flight prices by route and dates. The default "
            "tool for any concrete request like 'how much from Moscow to Dubai in July'. "
            "For round trips (return_at provided, one_way=false) this tool fires three "
            "parallel requests internally — round-trip, one-way outbound, one-way inbound — "
            "and returns all three. Pass `destination` empty with `unique=true` to discover "
            "cheap directions from the origin. Cities accept either IATA codes (3 letters) "
            "or names (Russian or English). Dates must be YYYY-MM or YYYY-MM-DD."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Origin city/airport — IATA code or name."},
                "destination": {
                    "type": "string",
                    "description": "Destination city/airport. Leave empty with unique=true to list cheap directions from origin.",
                },
                "departure_at": {
                    "type": "string",
                    "description": "Departure date YYYY-MM or YYYY-MM-DD.",
                },
                "return_at": {
                    "type": "string",
                    "description": "Return date YYYY-MM or YYYY-MM-DD. Empty for one-way.",
                },
                "one_way": {"type": "boolean", "description": "True for one-way; false (default) means round-trip."},
                "direct": {"type": "boolean", "description": "True = only non-stop flights."},
                "currency": {"type": "string", "description": "Currency code (rub/usd/eur). Default rub."},
                "sorting": {
                    "type": "string",
                    "enum": ["price", "route"],
                    "description": "price (default) or route (popularity).",
                },
                "unique": {
                    "type": "boolean",
                    "description": "True = only unique destinations. Use for 'where can I fly cheap from X' queries.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["origin"],
        }

    async def execute(
        self,
        origin: str,
        destination: str = "",
        departure_at: str = "",
        return_at: str = "",
        one_way: bool = False,
        direct: bool = False,
        currency: str = "rub",
        sorting: str = "price",
        unique: bool = False,
        limit: int = 30,
    ) -> str:
        origin_iata, err = _resolve(origin)
        if err:
            return _err(err)
        dest_iata: str | None = None
        if destination:
            dest_iata, err = _resolve(destination)
            if err:
                return _err(err)

        for field, val in (("departure_at", departure_at), ("return_at", return_at)):
            msg = _validate_date(val, field)
            if msg:
                return _err(msg)

        base = {
            "origin": origin_iata,
            "destination": dest_iata,
            "departure_at": departure_at or None,
            "direct": direct or None,
            "currency": currency,
            "sorting": sorting,
            "unique": unique or None,
            "limit": limit,
        }

        # One-way or no return date — single request.
        if one_way or not return_at:
            try:
                resp = await self._client.prices_for_dates(**base, one_way="true")
            except AviasalesAPIError as e:
                return _api_error(e)
            return _ok({"mode": "one_way", "tickets": normalize_list(resp)})

        # Round-trip — three parallel requests.
        rt_params = dict(base, return_at=return_at, one_way="false")
        out_params = dict(base, one_way="true")
        in_params = dict(
            base,
            origin=dest_iata,
            destination=origin_iata,
            departure_at=return_at,
            one_way="true",
        )

        results = await self._client.gather(
            self._client.prices_for_dates(**rt_params),
            self._client.prices_for_dates(**out_params),
            self._client.prices_for_dates(**in_params),
        )

        def _bucket(r: Any) -> dict[str, Any]:
            if isinstance(r, AviasalesAPIError):
                return {"error": f"Aviasales API ({r.status}): {r}", "tickets": []}
            if isinstance(r, Exception):
                return {"error": str(r), "tickets": []}
            return {"tickets": normalize_list(r)}

        return _ok(
            {
                "mode": "round_trip",
                "round_trip": _bucket(results[0]),
                "outbound": _bucket(results[1]),
                "inbound": _bucket(results[2]),
            }
        )


# ---------------------------------------------------------------------------
# aviasales_grouped_prices
# ---------------------------------------------------------------------------

class AviasalesGroupedPricesTool(_AviasalesBaseTool):
    """Grouped prices for 'when is it cheaper' queries."""

    @property
    def name(self) -> str:
        return "aviasales_grouped_prices"

    @property
    def description(self) -> str:
        return (
            "Cheapest tickets grouped by day or month. Use when the user is flexible "
            "on dates and wants to see when it's cheaper ('when is it cheaper to fly to "
            "Barcelona', 'which month is cheapest'). Use group_by=month for season-level "
            "questions, group_by=departure_at for day-level."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "group_by": {
                    "type": "string",
                    "enum": ["departure_at", "month"],
                    "description": "departure_at = group by day, month = group by month.",
                },
                "departure_at": {"type": "string", "description": "YYYY-MM or YYYY-MM-DD."},
                "return_at": {"type": "string", "description": "YYYY-MM or YYYY-MM-DD."},
                "direct": {"type": "boolean"},
                "min_trip_duration": {"type": "integer", "minimum": 1},
                "max_trip_duration": {"type": "integer", "minimum": 1},
                "currency": {"type": "string"},
            },
            "required": ["origin", "destination", "group_by"],
        }

    async def execute(
        self,
        origin: str,
        destination: str,
        group_by: str,
        departure_at: str = "",
        return_at: str = "",
        direct: bool = False,
        min_trip_duration: int | None = None,
        max_trip_duration: int | None = None,
        currency: str = "rub",
    ) -> str:
        origin_iata, err = _resolve(origin)
        if err:
            return _err(err)
        dest_iata, err = _resolve(destination)
        if err:
            return _err(err)
        for field, val in (("departure_at", departure_at), ("return_at", return_at)):
            msg = _validate_date(val, field)
            if msg:
                return _err(msg)

        try:
            resp = await self._client.grouped_prices(
                origin=origin_iata,
                destination=dest_iata,
                group_by=group_by,
                departure_at=departure_at or None,
                return_at=return_at or None,
                direct=direct or None,
                min_trip_duration=min_trip_duration,
                max_trip_duration=max_trip_duration,
                currency=currency,
            )
        except AviasalesAPIError as e:
            return _api_error(e)
        return _ok({"group_by": group_by, "tickets": normalize_list(resp)})


# ---------------------------------------------------------------------------
# aviasales_week_matrix
# ---------------------------------------------------------------------------

class AviasalesWeekMatrixTool(_AviasalesBaseTool):
    """Price grid for ±3/4 days around given departure/return dates."""

    @property
    def name(self) -> str:
        return "aviasales_week_matrix"

    @property
    def description(self) -> str:
        return (
            "Prices in a window of 3 days before and 4 days after the given departure "
            "and return dates. Use when the user has approximate dates and is willing "
            "to shift by a few days ('around May 15', '±2 days'). Always pair with "
            "aviasales_search_dates when the user signals date flexibility."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "depart_date": {"type": "string", "description": "YYYY-MM-DD anchor for departure."},
                "return_date": {"type": "string", "description": "YYYY-MM-DD anchor for return (empty for one-way)."},
                "currency": {"type": "string"},
            },
            "required": ["origin", "destination", "depart_date"],
        }

    async def execute(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str = "",
        currency: str = "rub",
    ) -> str:
        origin_iata, err = _resolve(origin)
        if err:
            return _err(err)
        dest_iata, err = _resolve(destination)
        if err:
            return _err(err)
        for field, val, allow_empty in (
            ("depart_date", depart_date, False),
            ("return_date", return_date, True),
        ):
            msg = _validate_date(val, field, allow_empty=allow_empty)
            if msg:
                return _err(msg)
            # week-matrix needs full YYYY-MM-DD specifically.
            if val and len(val) != 10:
                return _err(f"{field} должен быть в формате YYYY-MM-DD для week-matrix")

        try:
            resp = await self._client.week_matrix(
                origin=origin_iata,
                destination=dest_iata,
                depart_date=depart_date,
                return_date=return_date or None,
                currency=currency,
                show_to_affiliates="true",
            )
        except AviasalesAPIError as e:
            return _api_error(e)
        return _ok(normalize_week_matrix(resp))


# ---------------------------------------------------------------------------
# aviasales_price_range
# ---------------------------------------------------------------------------

class AviasalesPriceRangeTool(_AviasalesBaseTool):
    """Search tickets within a budget."""

    @property
    def name(self) -> str:
        return "aviasales_price_range"

    @property
    def description(self) -> str:
        return (
            "Search tickets within a price range. Use whenever the user states a budget "
            "('up to 10000₽', 'no more than 15k', 'within 20k'). Budget is the primary "
            "filter — prefer this tool over aviasales_search_dates when both budget and "
            "route are given."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "value_min": {"type": "number", "minimum": 0},
                "value_max": {"type": "number", "minimum": 0},
                "one_way": {"type": "boolean"},
                "direct": {"type": "boolean"},
                "currency": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                "page": {"type": "integer", "minimum": 1},
            },
            "required": ["origin"],
        }

    async def execute(
        self,
        origin: str,
        destination: str = "",
        value_min: float | None = None,
        value_max: float | None = None,
        one_way: bool = False,
        direct: bool = False,
        currency: str = "rub",
        limit: int = 30,
        page: int = 1,
    ) -> str:
        origin_iata, err = _resolve(origin)
        if err:
            return _err(err)
        dest_iata: str | None = None
        if destination:
            dest_iata, err = _resolve(destination)
            if err:
                return _err(err)

        try:
            resp = await self._client.search_by_price_range(
                origin=origin_iata,
                destination=dest_iata,
                value_min=value_min,
                value_max=value_max,
                one_way="true" if one_way else "false",
                direct=direct or None,
                currency=currency,
                limit=limit,
                page=page,
            )
        except AviasalesAPIError as e:
            return _api_error(e)
        return _ok({"tickets": normalize_list(resp)})


def build_tools(client: AviasalesClient) -> list[Tool]:
    """Convenience factory for nanobot.py wiring."""
    return [
        AviasalesSearchDatesTool(client),
        AviasalesGroupedPricesTool(client),
        AviasalesWeekMatrixTool(client),
        AviasalesPriceRangeTool(client),
    ]
