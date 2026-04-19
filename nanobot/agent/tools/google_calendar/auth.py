"""Google Calendar OAuth 2.0 authentication manager."""

import json
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from loguru import logger

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = "https://www.googleapis.com/auth/calendar"


class _StateEntry:
    __slots__ = ("user_id", "channel", "chat_id", "expires_at")

    def __init__(self, user_id: str, channel: str, chat_id: str, expires_at: float) -> None:
        self.user_id = user_id
        self.channel = channel
        self.chat_id = chat_id
        self.expires_at = expires_at


class _StateStore:
    """Short-lived CSRF state tokens: random string → _StateEntry."""

    _TTL = 600  # 10 minutes

    def __init__(self) -> None:
        self._store: dict[str, _StateEntry] = {}

    def create(self, user_id: str, channel: str, chat_id: str) -> str:
        self._purge()
        state = secrets.token_urlsafe(32)
        self._store[state] = _StateEntry(user_id, channel, chat_id, time.monotonic() + self._TTL)
        return state

    def pop(self, state: str) -> _StateEntry | None:
        """Consume a state token → _StateEntry, or None if missing/expired."""
        self._purge()
        entry = self._store.pop(state, None)
        if entry is None:
            return None
        return entry if time.monotonic() < entry.expires_at else None

    def _purge(self) -> None:
        now = time.monotonic()
        self._store = {k: v for k, v in self._store.items() if v.expires_at > now}


class _TokenStore:
    """Persistent token storage: JSON file keyed by user_id.

    Each entry holds access_token, refresh_token, and expires_at (Unix timestamp).
    Swapping the backend later (e.g. to a DB) means replacing this class only.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path).expanduser()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except Exception as e:
                logger.warning("gcal: failed to load token store {}: {}", self._path, e)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._data.get(user_id)

    def set(self, user_id: str, tokens: dict[str, Any]) -> None:
        self._data[user_id] = tokens
        self._save()

    def delete(self, user_id: str) -> None:
        self._data.pop(user_id, None)
        self._save()

    def has(self, user_id: str) -> bool:
        entry = self._data.get(user_id)
        return bool(entry and entry.get("refresh_token"))


class GoogleCalendarAuth:
    """OAuth 2.0 manager for Google Calendar.

    Responsibilities:
    - Build the authorization URL to send to the user
    - Handle the OAuth callback (exchange code → tokens)
    - Return a fresh access token for API calls, refreshing automatically
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_store_path: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._states = _StateStore()
        self._tokens = _TokenStore(token_store_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_auth_url(self, user_id: str, channel: str, chat_id: str) -> str:
        """Return a Google OAuth URL. Send this link to the user in Telegram."""
        state = self._states.create(user_id, channel, chat_id)
        params = urlencode({
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",   # request a refresh_token
            "prompt": "consent",        # always return refresh_token (even on re-auth)
            "state": state,
        })
        return f"{_AUTH_URL}?{params}"

    async def handle_callback(self, code: str, state: str) -> _StateEntry | None:
        """Called by the HTTP callback server after Google redirects.

        Exchanges the one-time code for tokens and persists them.
        Returns the state entry (user_id, channel, chat_id) on success,
        or None if the state token is invalid/expired.
        """
        entry = self._states.pop(state)
        if entry is None:
            logger.warning("gcal: invalid or expired OAuth state — possible CSRF attempt")
            return None

        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(_TOKEN_URL, data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                })
                r.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("gcal: token exchange failed: {}", e)
            return None

        tokens = r.json()
        tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
        self._tokens.set(entry.user_id, tokens)
        logger.info("gcal: user {} authorized", entry.user_id)
        return entry

    async def get_access_token(self, user_id: str) -> str | None:
        """Return a valid access token, refreshing silently if expired.

        Returns None if the user has never authorized or re-auth is required.
        """
        tokens = self._tokens.get(user_id)
        if not tokens:
            return None

        # 60-second buffer so we don't use a token that expires mid-request
        if time.time() < tokens.get("expires_at", 0) - 60:
            return tokens["access_token"]

        return await self._refresh(user_id, tokens)

    def is_authorized(self, user_id: str) -> bool:
        """True if the user has a stored refresh token."""
        return self._tokens.has(user_id)

    def revoke(self, user_id: str) -> None:
        """Remove stored tokens for a user (disconnect Google Calendar)."""
        self._tokens.delete(user_id)
        logger.info("gcal: revoked tokens for user {}", user_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _refresh(self, user_id: str, tokens: dict[str, Any]) -> str | None:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            logger.warning("gcal: no refresh token for user {}, re-auth required", user_id)
            self._tokens.delete(user_id)
            return None

        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(_TOKEN_URL, data={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                })
                r.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("gcal: token refresh failed for user {}: {}", user_id, e)
            return None

        refreshed = r.json()
        tokens["access_token"] = refreshed["access_token"]
        tokens["expires_at"] = time.time() + refreshed.get("expires_in", 3600)
        # Google may rotate the refresh token — persist the new one if present
        if "refresh_token" in refreshed:
            tokens["refresh_token"] = refreshed["refresh_token"]
        self._tokens.set(user_id, tokens)
        return tokens["access_token"]
