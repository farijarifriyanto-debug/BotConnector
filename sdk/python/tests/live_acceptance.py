import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from botconnector import BotConnector, BotConnectorError


def check(name, ok, extra=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + extra if extra else ''}")
    return ok


failed = False
try:
    chat = BotConnector(os.environ.get("BOTCONNECTOR_CHAT_URL", "http://127.0.0.1:11435/v1"))
    models = chat.models.list(); failed |= not check("PY_SDK_IMPORT", True, "stdlib client imported")
    failed |= not check("PY_SDK_MODELS", isinstance(models.get("data"), list), "GET /v1/models")
    response = chat.chat.create({"model": "local-model", "messages": [{"role": "user", "content": "Reply with PY-SDK-CHAT-OK"}], "max_tokens": 32})
    failed |= not check("PY_SDK_CHAT", bool(response.get("choices")), "POST /v1/chat/completions")
    events = list(chat.chat.stream({"model": "local-model", "messages": [{"role": "user", "content": "Reply briefly with PY-SDK-STREAM-OK"}], "max_tokens": 32}))
    failed |= not check("PY_SDK_STREAM", len(events) > 0, f"{len(events)} SSE events")
    embed_url = os.environ.get("BOTCONNECTOR_EMBED_URL")
    if embed_url:
        embedding = BotConnector(embed_url).embeddings.create({"model": "local-embed", "input": ["python first", "python second"]})
        vectors = [row.get("embedding", []) for row in embedding.get("data", [])]
        ok = len(vectors) == 2 and all(v and all(isinstance(x, (int, float)) for x in v) for v in vectors) and len(vectors[0]) == len(vectors[1])
        failed |= not check("PY_SDK_EMBEDDINGS", ok, f"n={len(vectors)} dim={len(vectors[0]) if vectors else 0}")
    else:
        failed |= not check("PY_SDK_EMBEDDINGS", False, "BOTCONNECTOR_EMBED_URL is not set")
    try:
        BotConnector("http://127.0.0.1:1/v1", timeout=0.3).models.list(); ok = False
    except BotConnectorError as exc:
        ok = exc.code == "NETWORK_ERROR"
    failed |= not check("PY_SDK_ERROR_HANDLING", ok, "normalized network error")
except Exception as exc:
    print(f"FAIL  PY_SDK_RUNTIME  — {exc}"); failed = True
raise SystemExit(1 if failed else 0)
