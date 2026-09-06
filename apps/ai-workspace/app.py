"""
BotConnector AI Workspace — lightweight AI workspaces for Study, Business, and Coding.

Served under botconnector.id/workspace (nginx strips the prefix). Public traffic is
rate-limited by nginx. The central admin cookie controls access to task="main".
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tools import coding, extract, study

BASE = Path(__file__).parent
APP_VERSION = "0.8.0"
app = FastAPI(title="BotConnector AI Workspace", version=APP_VERSION)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").encode()


def _verify_admin(token: str) -> str | None:
    if not token or "." not in token or not ADMIN_SECRET:
        return None
    body, signature = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(body.encode()).decode()
    except Exception:
        return None
    expected = hmac.new(ADMIN_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    email, _, expires_at = payload.partition("|")
    return email if expires_at.isdigit() and int(expires_at) >= time.time() else None


def _is_admin(request: Request) -> bool:
    return bool(_verify_admin(request.cookies.get("bc_admin", "")))


def _gate(request: Request, task: str) -> str:
    requested = "main" if task == "main" else "fast"
    return "fast" if requested == "main" and not _is_admin(request) else requested


class StudyReq(BaseModel):
    mode: str
    text: str = ""
    question: str = ""
    task: str = "fast"
    detail: str = "terstruktur"
    card_count: int = 8
    quiz_count: int = 5
    difficulty: str = "sedang"
    quiz_type: str = "pilihan_ganda"
    focus: str = ""


class CodeFileReq(BaseModel):
    name: str
    text: str = ""
    lang: str = ""


class CodingReq(BaseModel):
    mode: str
    code: str = ""
    desc: str = ""
    lang: str = "python"
    extra: str = ""
    question: str = ""
    task: str = "fast"
    files: list[CodeFileReq] = Field(default_factory=list)
    active_name: str = ""
    instruction: str = ""
    project_rules: str = ""
    context_pins: list[str] = Field(default_factory=list)
    context_excludes: list[str] = Field(default_factory=list)
    symbol_query: str = ""
    selection_start_line: int = 0
    selection_end_line: int = 0
    selection_text: str = ""
    context_mentions: list[str] = Field(default_factory=list)
    approved_plan_files: list[str] = Field(default_factory=list)


@app.get("/health")
async def health():
    return {"ok": True, "service": "ai-workspace", "version": APP_VERSION}


@app.get("/api/admin/status")
async def admin_status(request: Request):
    return {"admin": _is_admin(request), "login": "https://botconnector.id/panel"}


@app.post("/api/study")
async def api_study(req: StudyReq, request: Request):
    try:
        out = await study.run(
            mode=req.mode,
            text=req.text,
            question=req.question,
            task=_gate(request, req.task),
            detail=req.detail,
            card_count=req.card_count,
            quiz_count=req.quiz_count,
            difficulty=req.difficulty,
            quiz_type=req.quiz_type,
            focus=req.focus,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"gagal: {exc}") from exc
    if req.task == "main" and out.get("_meta") and not _is_admin(request):
        out["_gated"] = True
    return out


@app.post("/api/coding")
async def api_coding(req: CodingReq, request: Request):
    try:
        out = await coding.run(
            mode=req.mode,
            code=req.code,
            desc=req.desc,
            lang=req.lang,
            extra=req.extra,
            question=req.question,
            task=_gate(request, req.task),
            files=[{"name": f.name, "text": f.text, "lang": f.lang} for f in req.files],
            active_name=req.active_name,
            instruction=req.instruction,
            project_rules=req.project_rules,
            context_pins=req.context_pins,
            context_excludes=req.context_excludes,
            symbol_query=req.symbol_query,
            selection_start_line=req.selection_start_line,
            selection_end_line=req.selection_end_line,
            selection_text=req.selection_text,
            context_mentions=req.context_mentions,
            approved_plan_files=req.approved_plan_files,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"gagal: {exc}") from exc
    if req.task == "main" and out.get("_meta") and not _is_admin(request):
        out["_gated"] = True
    return out


@app.post("/api/extract")
async def api_extract(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "file terlalu besar (maks 15MB)")
    try:
        document = extract.extract_document(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"gagal baca file: {exc}") from exc
    return {
        "text": document["text"],
        "chars": len(document["text"]),
        "name": file.filename,
        "kind": document["kind"],
        "pages": document.get("pages"),
        "truncated": document["truncated"],
    }


@app.get("/")
async def index():
    return FileResponse(BASE / "static" / "index.html")
