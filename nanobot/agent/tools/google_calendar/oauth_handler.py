"""aiohttp handler factory for the Google Calendar OAuth callback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web
from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.tools.google_calendar.auth import GoogleCalendarAuth
    from nanobot.bus.queue import MessageBus

_HTML_SUCCESS = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Google Calendar connected</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
<h2>&#10003; Google Calendar connected</h2>
<p>You can close this tab and return to the chat.</p>
</body>
</html>
"""

_HTML_ERROR = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Authorization failed</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
<h2>&#10007; Authorization failed</h2>
<p>{reason}</p>
<p>Please try again by sending <b>connect google calendar</b> in the chat.</p>
</body>
</html>
"""


def make_gcal_oauth_handler(auth: "GoogleCalendarAuth", bus: "MessageBus"):
    """Return an aiohttp handler for GET /oauth/google_calendar/callback."""

    async def handle_callback(request: web.Request) -> web.Response:
        code = request.rel_url.query.get("code")
        state = request.rel_url.query.get("state")
        error = request.rel_url.query.get("error")

        if error or not code or not state:
            reason = error or "Missing code or state parameter"
            logger.warning("gcal: OAuth callback error: {}", reason)
            return web.Response(
                text=_HTML_ERROR.format(reason=reason),
                content_type="text/html",
                status=400,
            )

        entry = await auth.handle_callback(code, state)
        if entry is None:
            return web.Response(
                text=_HTML_ERROR.format(reason="Invalid or expired authorization session."),
                content_type="text/html",
                status=400,
            )

        # Notify the user in Telegram (or whatever channel they came from)
        from nanobot.bus.events import OutboundMessage
        try:
            await bus.publish_outbound(OutboundMessage(
                channel=entry.channel,
                chat_id=entry.chat_id,
                content="Google Calendar connected successfully! You can now ask me to manage your calendar.",
            ))
        except Exception as e:
            logger.error("gcal: failed to send authorization notification: {}", e)

        return web.Response(text=_HTML_SUCCESS, content_type="text/html")

    return handle_callback
