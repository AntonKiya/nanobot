"""City/airline IATA resolver.

Loads Travelpayouts reference JSON files (cities, airlines) once on first use
and serves IATA lookups in-memory. Designed for direct module-level access:
``resolve_city("Москва")`` / ``airline_name("SU")``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ASSETS = Path(__file__).resolve().parents[3] / "skills" / "aviasales-flights" / "assets"

_IATA_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class CityMatch:
    iata: str
    name: str
    country: str
    flightable: bool


class ResolverError(Exception):
    """Resolution failed in a way the agent should surface to the user."""


# --- Index built once on import --------------------------------------------

def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_city_index() -> tuple[dict[str, CityMatch], dict[str, list[CityMatch]]]:
    raw = _load_json(_ASSETS / "cities.json")
    by_iata: dict[str, CityMatch] = {}
    by_name: dict[str, list[CityMatch]] = {}
    for c in raw:
        iata = c.get("code")
        if not iata:
            continue
        match = CityMatch(
            iata=iata,
            name=c.get("name") or c.get("name_translations", {}).get("en") or iata,
            country=c.get("country_code") or "",
            flightable=bool(c.get("has_flightable_airport")),
        )
        by_iata[iata] = match
        names = {match.name}
        for v in (c.get("name_translations") or {}).values():
            if v:
                names.add(v)
        for n in names:
            key = n.strip().lower()
            if key:
                by_name.setdefault(key, []).append(match)
    return by_iata, by_name


def _build_airline_index() -> dict[str, str]:
    raw = _load_json(_ASSETS / "airlines.json")
    out: dict[str, str] = {}
    for a in raw:
        code = a.get("code")
        if not code:
            continue
        out[code] = a.get("name") or a.get("name_translations", {}).get("en") or code
    return out


_CITY_BY_IATA, _CITY_BY_NAME = _build_city_index()
_AIRLINE_BY_IATA = _build_airline_index()


# --- Public API -------------------------------------------------------------

def airline_name(code: str) -> str:
    """Return human-readable airline name for an IATA code (or the code if unknown)."""
    if not code:
        return ""
    return _AIRLINE_BY_IATA.get(code.upper(), code)


def resolve_city(query: str) -> CityMatch:
    """Resolve a user-provided city reference to a single CityMatch.

    Accepts an IATA code (3 uppercase letters) verbatim, otherwise looks up
    the name. Raises ResolverError with a human-readable message on
    ambiguous or missing matches — the agent surfaces it to the user.
    """
    if not query or not query.strip():
        raise ResolverError("город не указан")

    q = query.strip()

    if _IATA_RE.match(q):
        match = _CITY_BY_IATA.get(q)
        if match:
            return match
        # Unknown but well-formed IATA — trust it; API will reject if invalid.
        return CityMatch(iata=q, name=q, country="", flightable=True)

    matches = _CITY_BY_NAME.get(q.lower())
    if not matches:
        raise ResolverError(
            f"не нашёл город «{query}» в справочнике. Уточни название "
            "или передай IATA-код (3 буквы, например MOW)."
        )

    # Deduplicate by IATA — same city can appear under multiple names.
    unique: dict[str, CityMatch] = {}
    for m in matches:
        unique.setdefault(m.iata, m)
    candidates = list(unique.values())

    if len(candidates) == 1:
        return candidates[0]

    # Prefer flightable airports — non-flightable cities are rarely the answer.
    flightable = [c for c in candidates if c.flightable]
    if len(flightable) == 1:
        return flightable[0]
    if flightable:
        candidates = flightable

    if len(candidates) == 1:
        return candidates[0]

    options = ", ".join(f"{c.name} ({c.country}, {c.iata})" for c in candidates[:8])
    raise ResolverError(
        f"нашёл несколько городов с названием «{query}»: {options}. "
        "Уточни у пользователя какой имеется в виду и передай IATA-код."
    )
