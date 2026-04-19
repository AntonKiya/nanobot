"""Google Calendar API v3 client.

Thin httpx wrapper around the REST API. Handles auth token retrieval
and maps HTTP errors to readable messages. All event data is plain dicts
— the tools layer is responsible for constructing and interpreting them.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.google_calendar.auth import GoogleCalendarAuth

_BASE = "https://www.googleapis.com/calendar/v3"
_TIMEOUT = 10.0


class NotAuthorizedError(Exception):
    """User has not connected Google Calendar yet."""


class CalendarAPIError(Exception):
    """Google Calendar API returned an error."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class GoogleCalendarClient:
    """Async Google Calendar API v3 client."""

    def __init__(self, auth: GoogleCalendarAuth) -> None:
        self._auth = auth

    # ------------------------------------------------------------------
    # Calendars
    # ------------------------------------------------------------------

    async def list_calendars(self, user_id: str) -> list[dict[str, Any]]:
        """Return all calendars the user has access to."""
        data = await self._get(user_id, "/users/me/calendarList")
        return data.get("items", [])

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def list_events(
        self,
        user_id: str,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 50,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """List events in a time range, expanding recurring events into instances.

        Args:
            time_min/time_max: ISO 8601 timestamps (e.g. "2024-01-15T00:00:00Z").
            query:             Full-text search string (searches summary, description, etc.).
        """
        params: dict[str, Any] = {
            "singleEvents": "true",  # expand recurring events
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query

        data = await self._get(user_id, f"/calendars/{calendar_id}/events", params=params)
        return data.get("items", [])

    async def get_event(
        self, user_id: str, event_id: str, calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Return a single event by ID."""
        return await self._get(user_id, f"/calendars/{calendar_id}/events/{event_id}")

    async def create_event(
        self, user_id: str, event: dict[str, Any], calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Create a new event. Returns the created event resource.

        Event body examples:

        Timed event:
            {
                "summary": "Meeting",
                "start": {"dateTime": "2024-01-15T10:00:00", "timeZone": "Europe/Moscow"},
                "end":   {"dateTime": "2024-01-15T11:00:00", "timeZone": "Europe/Moscow"},
            }

        All-day event (end date is exclusive):
            {
                "summary": "Holiday",
                "start": {"date": "2024-01-15"},
                "end":   {"date": "2024-01-16"},
            }
        """
        return await self._post(user_id, f"/calendars/{calendar_id}/events", body=event)

    async def update_event(
        self,
        user_id: str,
        event_id: str,
        fields: dict[str, Any],
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Partially update an event (PATCH — only provided fields are changed)."""
        return await self._patch(
            user_id, f"/calendars/{calendar_id}/events/{event_id}", body=fields
        )

    async def delete_event(
        self, user_id: str, event_id: str, calendar_id: str = "primary"
    ) -> None:
        """Delete an event by ID."""
        await self._delete(user_id, f"/calendars/{calendar_id}/events/{event_id}")

    async def free_busy(
        self,
        user_id: str,
        calendar_ids: list[str],
        time_min: str,
        time_max: str,
    ) -> dict[str, Any]:
        """Return busy intervals for one or more calendars.

        Returns a dict keyed by calendar_id with lists of busy periods:
            {"primary": {"busy": [{"start": "...", "end": "..."}]}}
        """
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cid} for cid in calendar_ids],
        }
        data = await self._post(user_id, "/freeBusy", body=body)
        return data.get("calendars", {})

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _headers(self, user_id: str) -> dict[str, str]:
        token = await self._auth.get_access_token(user_id)
        if token is None:
            raise NotAuthorizedError(
                f"Google Calendar is not connected for user {user_id}. "
                "Use the gcal_connect tool to authorize."
            )
        return {"Authorization": f"Bearer {token}"}

    async def _get(
        self, user_id: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = await self._headers(user_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{_BASE}{path}", headers=headers, params=params)
        return self._parse(r)

    async def _post(
        self, user_id: str, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        headers = await self._headers(user_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(f"{_BASE}{path}", headers=headers, json=body)
        return self._parse(r)

    async def _patch(
        self, user_id: str, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        headers = await self._headers(user_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.patch(f"{_BASE}{path}", headers=headers, json=body)
        return self._parse(r)

    async def _delete(self, user_id: str, path: str) -> None:
        headers = await self._headers(user_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.delete(f"{_BASE}{path}", headers=headers)
        if r.status_code not in (200, 204):
            self._raise(r)

    @staticmethod
    def _parse(r: httpx.Response) -> dict[str, Any]:
        if r.status_code in (200, 201):
            return r.json()
        GoogleCalendarClient._raise(r)

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        try:
            message = r.json().get("error", {}).get("message", r.text)
        except Exception:
            message = r.text
        logger.warning("gcal: API error {} — {}", r.status_code, message)
        raise CalendarAPIError(r.status_code, f"Google Calendar API error {r.status_code}: {message}")
