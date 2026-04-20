"""Google Tasks API v1 client.

Thin httpx wrapper around the REST API. Mirrors the structure of client.py.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.google_calendar.auth import GoogleCalendarAuth
from nanobot.agent.tools.google_calendar.client import NotAuthorizedError, CalendarAPIError

_BASE = "https://tasks.googleapis.com/tasks/v1"
_TIMEOUT = 10.0


def _due_prefix(s: str) -> str:
    # Google Tasks returns "...T00:00:00.000Z"; callers pass "...T00:00:00Z".
    # Truncate to YYYY-MM-DDTHH:MM:SS so both formats compare correctly.
    return s[:19]


class GoogleTasksClient:
    """Async Google Tasks API v1 client."""

    def __init__(self, auth: GoogleCalendarAuth) -> None:
        self._auth = auth

    # ------------------------------------------------------------------
    # Task lists
    # ------------------------------------------------------------------

    async def list_tasklists(self, user_id: str) -> list[dict[str, Any]]:
        """Return all task lists for the user."""
        data = await self._get(user_id, "/users/@me/lists")
        return data.get("items", [])

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def list_tasks(
        self,
        user_id: str,
        tasklist_id: str = "@default",
        due_min: str | None = None,
        due_max: str | None = None,
        show_completed: bool = False,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """List tasks in a task list.

        Args:
            due_min/due_max: RFC 3339 timestamps to filter by due date.
            show_completed:  Include completed tasks (default False).
        """
        # Always fetch all tasks with showCompleted+showHidden — the API silently drops
        # completed tasks when date filters are applied. Filter client-side instead.
        params: dict[str, Any] = {
            "maxResults": max_results,
            "showCompleted": "true",
            "showHidden": "true",
        }

        data = await self._get(user_id, f"/lists/{tasklist_id}/tasks", params=params)
        items = data.get("items", [])

        if due_min:
            items = [t for t in items if t.get("due") and _due_prefix(t["due"]) >= _due_prefix(due_min)]
        if due_max:
            items = [t for t in items if t.get("due") and _due_prefix(t["due"]) < _due_prefix(due_max)]
        if not show_completed:
            items = [t for t in items if t.get("status") != "completed"]
        return items

    async def create_task(
        self,
        user_id: str,
        task: dict[str, Any],
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        """Create a new task. Returns the created task resource."""
        return await self._post(user_id, f"/lists/{tasklist_id}/tasks", body=task)

    async def update_task(
        self,
        user_id: str,
        task_id: str,
        fields: dict[str, Any],
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        """Partially update a task (PATCH)."""
        return await self._patch(user_id, f"/lists/{tasklist_id}/tasks/{task_id}", body=fields)

    async def delete_task(
        self,
        user_id: str,
        task_id: str,
        tasklist_id: str = "@default",
    ) -> None:
        """Delete a task by ID."""
        await self._delete(user_id, f"/lists/{tasklist_id}/tasks/{task_id}")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _headers(self, user_id: str) -> dict[str, str]:
        token = await self._auth.get_access_token(user_id)
        if token is None:
            raise NotAuthorizedError(
                f"Google Calendar/Tasks is not connected for user {user_id}. "
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
        GoogleTasksClient._raise(r)

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        try:
            message = r.json().get("error", {}).get("message", r.text)
        except Exception:
            message = r.text
        logger.warning("tasks: API error {} — {}", r.status_code, message)
        raise CalendarAPIError(r.status_code, f"Google Tasks API error {r.status_code}: {message}")
