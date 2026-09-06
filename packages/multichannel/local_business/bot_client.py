"""Minimal reliable Telegram Bot API client for BC Bisnis.

Supports both:
  - System Global Bot (@Botconector_Bot)
  - Customer-owned BYOB bots (via decrypted token)

Operations:
  getMe
  getUpdates  (long polling)
  sendMessage
  answerCallbackQuery
  getFile
  download file (to memory)
  sendDocument
  setWebhook
  deleteWebhook
  getWebhookInfo

Never logs or prints the token. Exception chaining is sanitized to prevent
httpx request URLs (which embed tokens) from leaking into tracebacks.
"""

from __future__ import annotations

import time
import logging
from typing import Any

import httpx

log = logging.getLogger("bc.bisnis.telegram")

API_BASE = "https://api.telegram.org/bot"
FILE_API_BASE = "https://api.telegram.org/file/bot"
DEFAULT_TIMEOUT = 15.0


class TelegramError(RuntimeError):
    pass


class _NoTokenLogTransport(httpx.HTTPTransport):
    """httpx transport that refuses to emit the request URL at INFO/DEBUG.

    httpx logs the full Bot API URL (including token) at INFO. We keep the
    transport quiet below WARNING so the secret URL never reaches journald.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


class BotApiClient:
    def __init__(self, token: str, timeout: float = DEFAULT_TIMEOUT):
        if not token:
            raise TelegramError("no bot token")
        self._token = token
        self._base = API_BASE + token
        self._file_base = FILE_API_BASE + token
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self._http = httpx.Client(
            timeout=timeout,
            transport=_NoTokenLogTransport(),
        )

    def __repr__(self) -> str:
        bot_id_part = self._token.split(":", 1)[0] if ":" in self._token else "redacted"
        return f"<BotApiClient bot_id={bot_id_part}>"

    def __str__(self) -> str:
        return self.__repr__()

    # low level ----------------------------------------------------
    def _call(self, method: str, params: dict | None = None, timeout: float | None = None, **kwargs) -> Any:
        try:
            r = self._http.post(
                f"{self._base}/{method}",
                json=params or {},
                timeout=timeout or self._http.timeout,
                **kwargs,
            )
        except httpx.HTTPError as e:
            # Explicitly break exception chain to prevent httpx URL (containing token) in traceback
            raise TelegramError(f"{method} network error: {type(e).__name__}") from None
        try:
            data = r.json()
        except Exception:
            raise TelegramError(f"{method} non-json response") from None
        if not data.get("ok"):
            desc = data.get("description", "unknown") if isinstance(data, dict) else "?"
            raise TelegramError(f"{method} api error: {desc}")
        return data.get("result")

    # getMe
    def get_me(self) -> dict:
        return self._call("getMe")

    # webhook management
    def get_webhook_info(self) -> dict:
        return self._call("getWebhookInfo")

    def set_webhook(
        self,
        url: str,
        secret_token: str | None = None,
        drop_pending_updates: bool = False,
        allowed_updates: list[str] | None = None,
    ) -> bool:
        params: dict[str, Any] = {
            "url": url,
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            params["secret_token"] = secret_token
        if allowed_updates is not None:
            params["allowed_updates"] = allowed_updates
        return bool(self._call("setWebhook", params))

    def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        return bool(self._call("deleteWebhook", {"drop_pending_updates": drop_pending_updates}))

    # long poll
    def get_updates(self, offset: int, timeout: int = 30, limit: int = 100) -> list[dict]:
        # Give httpx a socket read timeout slightly larger than Telegram long-poll timeout
        return self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "limit": limit},
            timeout=float(timeout + 5),
        )

    # messages
    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str = "",
    ) -> dict:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return self._call("sendMessage", params)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> bool:
        params = {"callback_query_id": callback_query_id, "text": text}
        return bool(self._call("answerCallbackQuery", params))

    def send_document(
        self,
        chat_id: int | str,
        filename: str,
        content: bytes,
        caption: str = "",
    ) -> dict:
        """Send a document via multipart/form-data sendDocument."""
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption
        try:
            r = self._http.post(
                f"{self._base}/sendDocument",
                data=fields,
                files={"document": (filename, content, "text/csv")},
            )
        except httpx.HTTPError as e:
            raise TelegramError(f"sendDocument network error: {type(e).__name__}") from None
        try:
            data = r.json()
        except Exception:
            raise TelegramError("sendDocument non-json response") from None
        if not data.get("ok"):
            desc = data.get("description", "unknown")
            raise TelegramError(f"sendDocument api error: {desc}")
        return data.get("result")

    def edit_message_reply_markup(
        self,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> dict:
        return self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup or {}},
        )

    def set_my_commands(self, commands: list[dict]) -> bool:
        return bool(self._call("setMyCommands", {"commands": commands}))

    def get_my_commands(self) -> list[dict]:
        return self._call("getMyCommands")

    # files
    def get_file(self, file_id: str) -> dict:
        return self._call("getFile", {"file_id": file_id})

    def download_file(self, file_path: str) -> bytes:
        url = f"{self._file_base}/{file_path}"
        try:
            r = self._http.get(url)
        except httpx.HTTPError as e:
            raise TelegramError(f"download error: {type(e).__name__}") from None
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise TelegramError(
                f"download error: HTTP {e.response.status_code}"
            ) from None
        return r.content

    def close(self):
        try:
            self._http.close()
        except Exception:
            pass


def retry_with_backoff(fn, attempts: int = 4, base_delay: float = 1.0):
    """Bounded retry with exponential backoff. Returns (result, None) or (None, exc)."""
    delay = base_delay
    last = None
    for _ in range(attempts):
        try:
            return fn(), None
        except TelegramError as e:
            last = e
            if "api error: 4" in str(last):  # Telegram 400 Bad Request
                return None, last
        time.sleep(delay)
        delay *= 2
    return None, last
