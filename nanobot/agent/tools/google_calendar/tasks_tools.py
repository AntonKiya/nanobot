"""Google Tasks tools for the nanobot agent."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.google_calendar.client import CalendarAPIError, NotAuthorizedError
from nanobot.agent.tools.google_calendar.tools import _GCalBaseTool, _ok, _not_authorized, _api_error
from nanobot.agent.tools.google_calendar.tasks_client import GoogleTasksClient


# ---------------------------------------------------------------------------
# gcal_list_tasklists
# ---------------------------------------------------------------------------

class GCalListTasklistsTool(_GCalBaseTool):
    """List all Google Task lists."""

    def __init__(self, client: GoogleTasksClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    @property
    def name(self) -> str:
        return "gcal_list_tasklists"

    @property
    def description(self) -> str:
        return "List all Google Task lists the user has (e.g. 'My Tasks', work lists, etc.)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **_: Any) -> str:
        try:
            lists = await self._client.list_tasklists(self._sender_id)
            result = [{"id": l.get("id"), "name": l.get("title")} for l in lists]
            return _ok(result)
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_list_tasks
# ---------------------------------------------------------------------------

class GCalListTasksTool(_GCalBaseTool):
    """List tasks from a Google Task list."""

    def __init__(self, client: GoogleTasksClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    @property
    def name(self) -> str:
        return "gcal_list_tasks"

    @property
    def description(self) -> str:
        return (
            "List tasks from a Google Task list. "
            "Use this alongside gcal_list_events to show a full picture of the user's day."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tasklist_id": {
                    "type": "string",
                    "description": "Task list ID. Use '@default' for the primary list (default).",
                },
                "due_min": {
                    "type": "string",
                    "description": "Filter tasks due after this date, RFC 3339 (e.g. '2024-01-15T00:00:00Z').",
                },
                "due_max": {
                    "type": "string",
                    "description": "Filter tasks due before this date, RFC 3339.",
                },
                "show_completed": {
                    "type": "boolean",
                    "description": "Include completed tasks (default false).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of tasks to return (default 50).",
                },
            },
            "required": [],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        tasklist_id: str = "@default",
        due_min: str | None = None,
        due_max: str | None = None,
        show_completed: bool = False,
        max_results: int = 50,
        **_: Any,
    ) -> str:
        try:
            tasks = await self._client.list_tasks(
                self._sender_id,
                tasklist_id=tasklist_id,
                due_min=due_min,
                due_max=due_max,
                show_completed=show_completed,
                max_results=max_results,
            )
            result = [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "due": t.get("due"),
                    "status": t.get("status"),
                    "notes": t.get("notes"),
                }
                for t in tasks
            ]
            return _ok(result)
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_create_task
# ---------------------------------------------------------------------------

class GCalCreateTaskTool(_GCalBaseTool):
    """Create a new task in Google Tasks."""

    def __init__(self, client: GoogleTasksClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    @property
    def name(self) -> str:
        return "gcal_create_task"

    @property
    def description(self) -> str:
        return (
            "Create a new task in Google Tasks. "
            "Use this when the user wants to add a to-do, reminder, or task — "
            "as opposed to gcal_create_event for meetings and time-blocked events."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title."},
                "due": {
                    "type": "string",
                    "description": (
                        "Due date/time in RFC 3339 format (e.g. '2024-01-15T00:00:00Z'). "
                        "For date-only deadlines use midnight UTC of that day."
                    ),
                },
                "notes": {"type": "string", "description": "Task description or notes."},
                "tasklist_id": {
                    "type": "string",
                    "description": "Task list ID (default: '@default').",
                },
            },
            "required": ["title"],
        }

    async def execute(
        self,
        title: str,
        due: str | None = None,
        notes: str | None = None,
        tasklist_id: str = "@default",
        **_: Any,
    ) -> str:
        task: dict[str, Any] = {"title": title}
        if due:
            task["due"] = due
        if notes:
            task["notes"] = notes

        try:
            created = await self._client.create_task(self._sender_id, task, tasklist_id)
            return _ok({
                "id": created.get("id"),
                "title": created.get("title"),
                "due": created.get("due"),
                "status": created.get("status"),
            })
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_complete_task
# ---------------------------------------------------------------------------

class GCalCompleteTaskTool(_GCalBaseTool):
    """Mark a Google Task as completed."""

    def __init__(self, client: GoogleTasksClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    @property
    def name(self) -> str:
        return "gcal_complete_task"

    @property
    def description(self) -> str:
        return (
            "Mark a task as completed. "
            "Use gcal_list_tasks to find the task_id first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Google Tasks task ID."},
                "tasklist_id": {
                    "type": "string",
                    "description": "Task list ID (default: '@default').",
                },
            },
            "required": ["task_id"],
        }

    async def execute(
        self, task_id: str, tasklist_id: str = "@default", **_: Any
    ) -> str:
        try:
            updated = await self._client.update_task(
                self._sender_id, task_id, {"status": "completed"}, tasklist_id
            )
            return _ok({"id": updated.get("id"), "title": updated.get("title"), "status": updated.get("status")})
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_update_task
# ---------------------------------------------------------------------------

class GCalUpdateTaskTool(_GCalBaseTool):
    """Update an existing Google Task."""

    def __init__(self, client: GoogleTasksClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    @property
    def name(self) -> str:
        return "gcal_update_task"

    @property
    def description(self) -> str:
        return (
            "Update a task's title, due date, or notes (PATCH — only provided fields are changed). "
            "Use gcal_list_tasks to find the task_id first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Google Tasks task ID."},
                "title": {"type": "string", "description": "New task title."},
                "due": {"type": "string", "description": "New due date/time, RFC 3339."},
                "notes": {"type": "string", "description": "New notes/description."},
                "tasklist_id": {
                    "type": "string",
                    "description": "Task list ID (default: '@default').",
                },
            },
            "required": ["task_id"],
        }

    async def execute(
        self,
        task_id: str,
        title: str | None = None,
        due: str | None = None,
        notes: str | None = None,
        tasklist_id: str = "@default",
        **_: Any,
    ) -> str:
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if due is not None:
            fields["due"] = due
        if notes is not None:
            fields["notes"] = notes

        if not fields:
            return "Не переданы поля для обновления."

        try:
            updated = await self._client.update_task(self._sender_id, task_id, fields, tasklist_id)
            return _ok({
                "id": updated.get("id"),
                "title": updated.get("title"),
                "due": updated.get("due"),
                "status": updated.get("status"),
            })
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# gcal_delete_task
# ---------------------------------------------------------------------------

class GCalDeleteTaskTool(_GCalBaseTool):
    """Delete a task from Google Tasks."""

    def __init__(self, client: GoogleTasksClient) -> None:
        self._client = client
        self._sender_id: str = ""
        self._channel: str = ""
        self._chat_id: str = ""

    @property
    def name(self) -> str:
        return "gcal_delete_task"

    @property
    def description(self) -> str:
        return (
            "Delete a task by ID. "
            "Use gcal_list_tasks to find the task_id first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Google Tasks task ID to delete."},
                "tasklist_id": {
                    "type": "string",
                    "description": "Task list ID (default: '@default').",
                },
            },
            "required": ["task_id"],
        }

    async def execute(
        self, task_id: str, tasklist_id: str = "@default", **_: Any
    ) -> str:
        try:
            await self._client.delete_task(self._sender_id, task_id, tasklist_id)
            return _ok({"deleted": True, "task_id": task_id})
        except NotAuthorizedError:
            return _not_authorized()
        except CalendarAPIError as e:
            return _api_error(e)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_task_tools(client: GoogleTasksClient) -> list[_GCalBaseTool]:
    """Return all Google Tasks tools sharing a single client."""
    return [
        GCalListTasklistsTool(client),
        GCalListTasksTool(client),
        GCalCreateTaskTool(client),
        GCalCompleteTaskTool(client),
        GCalUpdateTaskTool(client),
        GCalDeleteTaskTool(client),
    ]
