import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Generator, Iterable, Optional, Union


class BotConnectorError(RuntimeError):
    def __init__(self, message: str, status: int = 0, code: str = "BOTCONNECTOR_ERROR", body: Any = None):
        super().__init__(message)
        self.status, self.code, self.body = status, code, body


class _Resource:
    def __init__(self, client: "BotConnector"):
        self.client = client


class _Models(_Resource):
    def list(self) -> Dict[str, Any]: return self.client._request("/models")
    def get(self, model_id: str) -> Dict[str, Any]: return self.client._request("/models/" + urllib.parse.quote(model_id, safe=""))


class _Chat(_Resource):
    def create(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(request); payload["stream"] = False
        return self.client._request("/chat/completions", "POST", payload)
    def stream(self, request: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        payload = dict(request); payload["stream"] = True
        yield from self.client._stream("/chat/completions", payload)


class _Embeddings(_Resource):
    def create(self, request: Dict[str, Any]) -> Dict[str, Any]: return self.client._request("/embeddings", "POST", request)


class _Runtime(_Resource):
    def status(self) -> Dict[str, Any]:
        health = self.client._request_origin("/health")
        try: models = self.client.models.list()
        except BotConnectorError: models = None
        return {"healthy": health.get("status") in ("ok", "ready") if isinstance(health, dict) else bool(health), "status": health.get("status", "ok") if isinstance(health, dict) else "ok", "models": models}


class BotConnector:
    def __init__(self, base_url: str = "http://127.0.0.1:11435/v1", api_key: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = max(0.25, float(timeout))
        self.models, self.chat, self.embeddings, self.runtime = _Models(self), _Chat(self), _Embeddings(self), _Runtime(self)

    def _url(self, path: str) -> str: return self.base_url + "/" + path.lstrip("/")
    def _headers(self, stream: bool = False) -> Dict[str, str]:
        h = {"Accept": "text/event-stream" if stream else "application/json"}
        if self.api_key: h["Authorization"] = "Bearer " + self.api_key
        return h
    def _parse_error(self, exc: urllib.error.HTTPError) -> BotConnectorError:
        raw = exc.read().decode("utf-8", "replace")
        try: body = json.loads(raw)
        except ValueError: body = raw
        return BotConnectorError((body.get("error", {}).get("message") if isinstance(body, dict) else None) or f"BotConnector API returned {exc.code}", exc.code, "HTTP_ERROR", body)
    def _request(self, path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = self._headers();
        if body is not None: headers["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(self._url(path), data=data, headers=headers, method=method), timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc: raise self._parse_error(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc: raise BotConnectorError(str(exc), code="NETWORK_ERROR") from exc
    def _request_origin(self, path: str) -> Dict[str, Any]:
        from urllib.parse import urlsplit
        u = urlsplit(self.base_url); return BotConnector(u.scheme + "://" + u.netloc, self.api_key, self.timeout)._request(path)
    def _stream(self, path: str, body: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        data = json.dumps(body).encode("utf-8"); headers = self._headers(True); headers["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(self._url(path), data=data, headers=headers, method="POST"), timeout=self.timeout) as response:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"): continue
                    payload = line[5:].strip()
                    if payload == "[DONE]": return
                    try: yield json.loads(payload)
                    except ValueError as exc: raise BotConnectorError("Malformed SSE event from BotConnector", code="MALFORMED_STREAM") from exc
        except urllib.error.HTTPError as exc: raise self._parse_error(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc: raise BotConnectorError(str(exc), code="NETWORK_ERROR") from exc
