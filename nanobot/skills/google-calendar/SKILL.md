---
name: google-calendar
description: "Manage the user's Google Calendar: list, search, create, update, delete events; check free/busy slots; list calendars. TRIGGER when: user wants to see schedule, add/move/cancel an event, check availability, or find events by topic — even if Google Calendar is not mentioned by name."
---

# Google Calendar Skill

Help the user manage their Google Calendar with minimal friction.

## Authorization

Before any calendar operation, check whether the user is authorized:
- Use `gcal_list_calendars` as a lightweight probe — if it returns `not_authorized`, the user has not connected their Google account.
- On `not_authorized`: call `gcal_connect` to generate an authorization link, send it to the user with a short explanation ("Click this link to connect your Google Calendar"), and stop. Do not attempt any other calendar tool.
- Do not ask the user to authorize more than once per conversation unless they explicitly say authorization failed.

## Workflow

1. Understand what the user wants (see trigger categories below).
2. If the intent requires a specific event and none was mentioned, search or list first to confirm the right event before modifying or deleting.
3. If critical details are missing (e.g. no time for a new event), ask one short clarification round — max 2–3 questions in a single message.
4. Execute the operation.
5. Confirm what was done in a brief, human-readable response.

## Events vs Tasks

Google Calendar has two distinct entity types — always distinguish them:

- **Event** (`gcal_*` calendar tools) — has a start and end time, occupies a slot in the schedule. Meetings, appointments, reminders with duration.
- **Task** (`gcal_*` tasks tools) — has only a due date/time (single point), no duration. To-dos, checklists, things "to do by X".

When the user asks "what do I have today" or "show my schedule" — **always** call **both** `gcal_list_events` and `gcal_list_tasks` for the requested period and present a unified list. Never show only events without tasks. Mark each item's type (e.g. "📅 Meeting with John 14:00–15:00" vs "✅ Submit report — due today").

**Strict scope**: only show results for the period the user asked about. If asked about today — show today only. Do not add "upcoming tasks" or "tasks for the rest of the week" unless explicitly requested.

When the user says "add a task / to-do / reminder" → `gcal_create_task`.
When the user says "schedule a meeting / block time / add an appointment" → `gcal_create_event`.
When ambiguous → default to event if a time range is given, task if only a deadline is given.

## Trigger Categories and Tools

**View schedule / upcoming events**
- Use `gcal_list_events` with `time_min` = start of requested period, `time_max` = start of the NEXT day after the period ends.
- `time_max` is exclusive — to include all-day events on April 20, use `time_max: 2026-04-21T00:00:00Z`, not `2026-04-20T23:59:59Z`.
- Default range if not specified: next 7 days.

**Search for a specific event**
- Use `gcal_search_events` with the user's keywords.
- If results are ambiguous (multiple matches), show a short list and ask which one they mean.

**Create an event**
- Use `gcal_create_event`.
- Required: `summary` (title), `start`, `end`.
- If the user gives a duration but no end time, compute it.
- If no time is given at all, ask before proceeding.
- Use `_build_time` logic: if the user gives a date only (no clock time), treat as all-day event (`date` format); otherwise use `dateTime` format.
- Default `calendar_id`: `"primary"`.

**Update an event**
- Use `gcal_update_event` with only the fields that need to change (PATCH semantics — unspecified fields are preserved).
- If the target event is ambiguous, search first.

**Delete an event**
- Use `gcal_delete_event`.
- Always confirm the event title and time with the user before deleting, unless they already identified it unambiguously.
- If the target event is ambiguous, search first.

**List tasks**
- Use `gcal_list_tasks`. Optionally pass `due_min`/`due_max` to filter by date range.
- `due_max` is exclusive — to include tasks due on April 20, set `due_max: 2026-04-21T00:00:00Z`.
- Tasks with no due date are not returned when filtering by date — mention them separately if relevant.
- User asks "show all tasks" → call without date filters, group: overdue → due today → upcoming → no deadline.
- Only set `show_completed: true` when the user explicitly asks to see completed tasks.

**Create a task**
- Use `gcal_create_task`.
- Required: `title`. Optional: `due` (RFC 3339), `notes`, `tasklist_id`.
- `due` is a single deadline point, not a range. If the user says "by Friday", set `due` to end of Friday.
- Default `tasklist_id`: `"@default"` (primary task list).

**Complete a task**
- Use `gcal_complete_task` with `task_id`.
- If target is ambiguous, call `gcal_list_tasks` first.

**Update a task**
- Use `gcal_update_task` with only the fields that need to change.
- If target is ambiguous, call `gcal_list_tasks` first.

**Delete a task**
- Use `gcal_delete_task`.
- Always confirm the task title with the user before deleting unless already unambiguous.

**List task lists**
- Use `gcal_list_tasklists` when the user refers to a named list ("work tasks", "shopping").
- Resolve the name to a `tasklist_id`, then pass it to task tools.

**Check availability / free slots**
- Use `gcal_free_busy` with the calendars and time range in question.
- If the user asks "am I free at X", check `primary` calendar by default.
- Report free slots in human-readable form, not raw JSON.

**List calendars**
- Use `gcal_list_calendars`.
- Useful when the user refers to a named calendar (work, personal, shared) — resolve the name to a `calendar_id` first.

## Clarification Policy

Ask only when missing information would make the operation wrong or ambiguous:
- No time provided for a new event
- Multiple events match a search and the user must pick one
- The user says "tomorrow's meeting" but there are several meetings tomorrow

Do not ask when:
- A sensible default exists (e.g. primary calendar, 1-hour duration)
- The user's phrasing already narrows it down enough for a practical choice

One clarification round only. Max 2–3 short questions in a single message.

## Timezone

Always use the timezone from context (system timezone or user preference). When creating or updating events, pass the timezone explicitly in `dateTime` fields. Never assume UTC for user-facing times unless the user is clearly working in UTC.

## Response Format

**On success (view/search):**
List events in a compact, readable format: title, date/time, optionally location. No raw IDs.

**On success (create/update/delete):**
One short confirmation sentence. Include the event title and time so the user can verify.

**On partial failure:**
Clearly state what succeeded and what failed. Do not silently skip failures.

**On not_authorized:**
Send the auth link from `gcal_connect`. One sentence of explanation. Stop.

## Error Handling

- `not_authorized`: trigger auth flow (see Authorization section).
- Event not found: tell the user and offer to search for it.
- API error: report the error briefly, suggest retrying. Do not retry automatically more than once.
- Ambiguous target: show candidates, ask which one. Do not guess.
