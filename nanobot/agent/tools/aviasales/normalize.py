"""Shape raw Travelpayouts API responses into a compact form for the agent.

The agent should receive only the fields it needs to talk to the user:
price, airline (IATA + human name), dates, transfers, full deeplink, and
an `is_expired` flag (never silently dropped — agent decides how to phrase).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nanobot.agent.tools.aviasales.resolver import airline_name

_AVIASALES_PREFIX = "https://www.aviasales.ru"


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        # API returns ISO 8601 with timezone, e.g. "2026-04-29T10:23:11Z"
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt < datetime.now(timezone.utc)


def _full_link(link: str | None) -> str:
    if not link:
        return ""
    if link.startswith("http"):
        return link
    if not link.startswith("/"):
        link = "/" + link
    return _AVIASALES_PREFIX + link


def normalize_ticket(raw: dict[str, Any]) -> dict[str, Any]:
    """Compact a single ticket from prices_for_dates / search_by_price_range."""
    airline_code = raw.get("airline", "")
    return {
        "price": raw.get("price"),
        "currency": raw.get("currency"),
        "airline": airline_code,
        "airline_name": airline_name(airline_code),
        "flight_number": raw.get("flight_number"),
        "departure_at": raw.get("departure_at"),
        "return_at": raw.get("return_at"),
        "transfers": raw.get("transfers"),
        "return_transfers": raw.get("return_transfers"),
        "duration": raw.get("duration"),
        "duration_to": raw.get("duration_to"),
        "duration_back": raw.get("duration_back"),
        "origin": raw.get("origin"),
        "destination": raw.get("destination"),
        "link": _full_link(raw.get("link")),
        "is_expired": _is_expired(raw.get("expires_at")),
        "expires_at": raw.get("expires_at"),
    }


def normalize_list(raw_resp: dict[str, Any]) -> list[dict[str, Any]]:
    data = raw_resp.get("data") or []
    if isinstance(data, dict):
        # Some endpoints (grouped_prices) return {date: ticket} or nested dicts.
        out: list[dict[str, Any]] = []
        for key, value in data.items():
            if isinstance(value, dict) and "price" in value:
                ticket = normalize_ticket(value)
                ticket["group_key"] = key
                out.append(ticket)
            elif isinstance(value, dict):
                # nested {origin: {destination: ticket}}
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, dict) and "price" in sub_value:
                        ticket = normalize_ticket(sub_value)
                        ticket["group_key"] = key
                        ticket["sub_key"] = sub_key
                        out.append(ticket)
        return out
    return [normalize_ticket(t) for t in data if isinstance(t, dict)]


def normalize_week_matrix(raw_resp: dict[str, Any]) -> dict[str, Any]:
    """week-matrix returns {data: [...], currency: ...} with a flat list of cells."""
    cells = raw_resp.get("data") or []
    out = []
    for c in cells:
        if not isinstance(c, dict):
            continue
        airline_code = c.get("airline", "") or c.get("gate", "")
        out.append(
            {
                "depart_date": c.get("depart_date"),
                "return_date": c.get("return_date"),
                "price": c.get("value"),
                "currency": raw_resp.get("currency"),
                "airline": airline_code,
                "airline_name": airline_name(airline_code) if airline_code else "",
                "transfers": c.get("number_of_changes"),
                "trip_class": c.get("trip_class"),
                "found_at": c.get("found_at"),
            }
        )
    return {"currency": raw_resp.get("currency"), "matrix": out}
