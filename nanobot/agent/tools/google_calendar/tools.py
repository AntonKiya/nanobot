"""Google Calendar tools for the nanobot agent."""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.google_calendar.auth import GoogleCalendarAuth
from nanobot.agent.tools.google_calendar.client import (
    CalendarAPIError,
    GoogleCalendarClient,
    NotAuthorizedError,
)


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _not_authorized() -> str:
    return "Google Calendar не подключён. Вызови gcal_connect чтобы авторизоваться."


def _api_error(e: CalendarAPIError) -> str:
    return f"Ошибка Google Calendar API ({e.status}): {e}"


class _GCalBaseTool(Tool):
    """Base class for all Google Calendar tools.

    Receives user context (sender_id, channel, chat_id) automatically
    before each tool call via set_user_context() called by the agent loop.
    """

    def __init__(self, client: GoogleCalendarClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    def set_user_context(self, sender_id: str | None, channel: str, chat_id: str) -> None:
        self._sender_id = sender_id or ""
        self._channel = channel
        self._chat_id = chat_id

    @property
    def read_only(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# gcal_connect
# ---------------------------------------------------------------------------

class GCalConnectTool(_GCalBaseTool):
    """Initiate Google Calendar OAuth authorization for the current user."""

    @property
    def name(self) -> str:
        return "gcal_connect"

    @property
    def description(self) -> str:
        return (
            "Generate a Google OAuth link so the user can connect their Google Calendar. "
            "Call this when the user asks to connect Calendar or when gcal_* tools return "
            "a 'not authorized' message. Returns a URL to send to the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **_: Any) -> str:
        if not self._sender_id:
            return "Ошибка: не удалось определить пользователя."
        url = self._client._auth.build_auth_url(self._sender_id, self._channel, self._chat_id)
        return (
            f"Отправь пользователю эту ссылку для подключения Google Calendar:\n\n{url}\n\n"
            "После авторизации он получит подтверждение в этот чат автоматически."
        )


# ---------------------------------------------------------------------------
# gcal_list_calendars
# ---------------------------------------------------------------------------

class GCalListCalendarsTool(_GCalBaseTool):
    """List all Google Calendars available to the user."""

    @property
    def name(self) -> str:
        return "gcal_list_calendars"

    @property
    def description(self) -> str:
        return "List all Google Calendars the user has access to (personal, work, shared, etc.)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **_: Any) -> str:
        try:
            calendars = await self._client.list_calendars(self._sender_id)
            result = [
                {"id": c.get("id"), "name": c.get("summary"), "primary": c.get("primary", False)}
                for c in calendars
            ]
            return _ok(result)
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_list_events
# ---------------------------------------------------------------------------

class GCalListEventsTool(_GCalBaseTool):
    """List upcoming events from Google Calendar."""

    @property
    def name(self) -> str:
        return "gcal_list_events"

    @property
    def description(self) -> str:
        return (
            "List events from Google Calendar for a given time range. "
            "Use this to check the schedule for a day, week, or any period."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "time_min": {
                    "type": "string",
                    "description": "Start of range, ISO 8601 (e.g. '2024-01-15T00:00:00Z').",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of range, ISO 8601 (e.g. '2024-01-15T23:59:59Z').",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Use 'primary' for the main calendar (default).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of events to return (default 50).",
                },
            },
            "required": [],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        time_min: str | None = None,
        time_max: str | None = None,
        calendar_id: str = "primary",
        max_results: int = 50,
        **_: Any,
    ) -> str:
        try:
            events = await self._client.list_events(
                self._sender_id,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                max_results=max_results,
            )
            return _ok(events)
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_search_events
# ---------------------------------------------------------------------------

class GCalSearchEventsTool(_GCalBaseTool):
    """Search events by text across Google Calendar."""

    @property
    def name(self) -> str:
        return "gcal_search_events"

    @property
    def description(self) -> str:
        return (
            "Search for events by text query (searches title, description, location). "
            "Optionally filter by time range."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for in event title, description, or location.",
                },
                "time_min": {
                    "type": "string",
                    "description": "Optional start of search range, ISO 8601.",
                },
                "time_max": {
                    "type": "string",
                    "description": "Optional end of search range, ISO 8601.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID (default: 'primary').",
                },
            },
            "required": ["query"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        query: str,
        time_min: str | None = None,
        time_max: str | None = None,
        calendar_id: str = "primary",
        **_: Any,
    ) -> str:
        try:
            events = await self._client.list_events(
                self._sender_id,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                query=query,
            )
            return _ok(events)
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_create_event
# ---------------------------------------------------------------------------

class GCalCreateEventTool(_GCalBaseTool):
    """Create a new event in Google Calendar."""

    @property
    def name(self) -> str:
        return "gcal_create_event"

    @property
    def description(self) -> str:
        return (
            "Create a new event in Google Calendar. "
            "For timed events provide start/end as 'YYYY-MM-DDTHH:MM:SS' plus timezone. "
            "For all-day events provide start/end as 'YYYY-MM-DD' (end is exclusive: +1 day)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start": {
                    "type": "string",
                    "description": "Start datetime ('2024-01-15T10:00:00') or date ('2024-01-15').",
                },
                "end": {
                    "type": "string",
                    "description": "End datetime or date. For all-day events, end is exclusive (+1 day).",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone for timed events (e.g. 'Europe/Moscow'). Ignored for all-day.",
                },
                "description": {"type": "string", "description": "Event description or notes."},
                "location": {"type": "string", "description": "Event location."},
                "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')."},
            },
            "required": ["summary", "start", "end"],
        }

    async def execute(
        self,
        summary: str,
        start: str,
        end: str,
        timezone: str | None = None,
        description: str | None = None,
        location: str | None = None,
        calendar_id: str = "primary",
        **_: Any,
    ) -> str:
        event: dict[str, Any] = {"summary": summary}
        event["start"] = _build_time(start, timezone)
        event["end"] = _build_time(end, timezone)
        if description:
            event["description"] = description
        if location:
            event["location"] = location

        try:
            created = await self._client.create_event(self._sender_id, event, calendar_id)
            return _ok({"id": created.get("id"), "summary": created.get("summary"),
                        "start": created.get("start"), "end": created.get("end"),
                        "htmlLink": created.get("htmlLink")})
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_update_event
# ---------------------------------------------------------------------------

class GCalUpdateEventTool(_GCalBaseTool):
    """Update an existing Google Calendar event."""

    @property
    def name(self) -> str:
        return "gcal_update_event"

    @property
    def description(self) -> str:
        return (
            "Update an existing event. Only provided fields are changed (PATCH). "
            "Use gcal_search_events or gcal_list_events to find the event_id first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Google Calendar event ID."},
                "summary": {"type": "string", "description": "New event title."},
                "start": {"type": "string", "description": "New start datetime or date."},
                "end": {"type": "string", "description": "New end datetime or date."},
                "timezone": {"type": "string", "description": "IANA timezone for timed events."},
                "description": {"type": "string", "description": "New description."},
                "location": {"type": "string", "description": "New location."},
                "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')."},
            },
            "required": ["event_id"],
        }

    async def execute(
        self,
        event_id: str,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        description: str | None = None,
        location: str | None = None,
        calendar_id: str = "primary",
        **_: Any,
    ) -> str:
        fields: dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if start is not None:
            fields["start"] = _build_time(start, timezone)
        if end is not None:
            fields["end"] = _build_time(end, timezone)
        if description is not None:
            fields["description"] = description
        if location is not None:
            fields["location"] = location

        if not fields:
            return "Не переданы поля для обновления."

        try:
            updated = await self._client.update_event(self._sender_id, event_id, fields, calendar_id)
            return _ok({"id": updated.get("id"), "summary": updated.get("summary"),
                        "start": updated.get("start"), "end": updated.get("end")})
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_delete_event
# ---------------------------------------------------------------------------

class GCalDeleteEventTool(_GCalBaseTool):
    """Delete an event from Google Calendar."""

    @property
    def name(self) -> str:
        return "gcal_delete_event"

    @property
    def description(self) -> str:
        return (
            "Delete an event from Google Calendar by event ID. "
            "Use gcal_search_events to find the event_id first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Google Calendar event ID to delete."},
                "calendar_id": {"type": "string", "description": "Calendar ID (default: 'primary')."},
            },
            "required": ["event_id"],
        }

    async def execute(self, event_id: str, calendar_id: str = "primary", **_: Any) -> str:
        try:
            await self._client.delete_event(self._sender_id, event_id, calendar_id)
            return _ok({"deleted": True, "event_id": event_id})
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_free_busy
# ---------------------------------------------------------------------------

class GCalFreeBusyTool(_GCalBaseTool):
    """Check free/busy slots in Google Calendar."""

    @property
    def name(self) -> str:
        return "gcal_free_busy"

    @property
    def description(self) -> str:
        return (
            "Check busy time slots for a given period. "
            "Returns busy intervals — gaps between them are free slots."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "time_min": {
                    "type": "string",
                    "description": "Start of period, ISO 8601 (e.g. '2024-01-15T09:00:00Z').",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of period, ISO 8601 (e.g. '2024-01-15T18:00:00Z').",
                },
                "calendar_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Calendar IDs to check (default: ['primary']).",
                },
            },
            "required": ["time_min", "time_max"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        time_min: str,
        time_max: str,
        calendar_ids: list[str] | None = None,
        **_: Any,
    ) -> str:
        try:
            result = await self._client.free_busy(
                self._sender_id,
                calendar_ids=calendar_ids or ["primary"],
                time_min=time_min,
                time_max=time_max,
            )
            return _ok(result)
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_time(dt_str: str, timezone: str | None) -> dict[str, str]:
    """Convert a date/datetime string to a Google Calendar time object."""
    if "T" in dt_str:
        result: dict[str, str] = {"dateTime": dt_str}
        if timezone:
            result["timeZone"] = timezone
        return result
    return {"date": dt_str}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_tools(auth: GoogleCalendarAuth) -> list[_GCalBaseTool]:
    """Return all Google Calendar tools sharing a single client."""
    client = GoogleCalendarClient(auth)
    return [
        GCalConnectTool(client),
        GCalListCalendarsTool(client),
        GCalListEventsTool(client),
        GCalSearchEventsTool(client),
        GCalCreateEventTool(client),
        GCalUpdateEventTool(client),
        GCalDeleteEventTool(client),
        GCalFreeBusyTool(client),
    ]
