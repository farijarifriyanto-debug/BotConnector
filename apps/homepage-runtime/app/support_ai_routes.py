"""
BotConnector AI Support V3 — FastAPI Route Handlers.
Exposes public & authenticated support AI endpoints with session resolution, rate limits, and ticket workflows.
"""
from __future__ import annotations

import os
import json
import uuid
import time
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse

from app.support_ai_service import SupportAIService
from app.support_ai_tools import ToolDispatcher, TICKET_DRAFTS
from app.support_ai_inference import GLOBAL_INFERENCE
from app.support_ai_knowledge import KNOWLEDGE_VERSION, CANONICAL_CHUNKS
from app.support import ticket_mgr, get_pg_credentials
import psycopg
from psycopg.rows import dict_row

router = APIRouter(prefix="/v1/support-ai", tags=["Support AI"])

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    ecosystem: Optional[str] = "PLATFORM"
    module: Optional[str] = "General"

class TicketDraftRequest(BaseModel):
    subject: str
    category: str = "GENERAL"
    summary: str
    steps_attempted: Optional[str] = None

class TicketConfirmRequest(BaseModel):
    draft_id: str
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None

def get_client_ip(request: Request) -> str:
    """Extract true client IP behind nginx proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def resolve_server_user_session(request: Request) -> Optional[Dict[str, Any]]:
    """
    IDOR-safe server session resolver.
    Derives authenticated user identity and entitlements strictly from bc_session in PostgreSQL.
    """
    token = request.cookies.get("bc_session")
    if not token:
        return None

    try:
        creds = get_pg_credentials()
        with psycopg.connect(
            host=creds["host"],
            port=creds["port"],
            dbname=creds["dbname"],
            user=creds["user"],
            password=creds["password"],
            row_factory=dict_row
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.user_id, u.email, u.name
                    FROM account_sessions s
                    JOIN users u ON u.id = s.user_id
                    WHERE s.token = %s AND s.revoked_at IS NULL AND s.expires_at > NOW()
                    LIMIT 1
                    """,
                    (token,)
                )
                row = cur.fetchone()
                if row:
                    return {
                        "user_id": str(row["user_id"]),
                        "email": row["email"],
                        "name": row.get("name") or row["email"].split("@")[0]
                    }
    except Exception:
        pass
    return None

@router.get("/health")
def support_ai_health():
    """Sanitized health check for readiness monitoring."""
    inf_health = GLOBAL_INFERENCE.health()
    return {
        "ok": True,
        "service": "BotConnector AI Support V3",
        "status": inf_health["status"],
        "free_models_first": inf_health["free_models_first"],
        "paid_fallback": inf_health["paid_fallback"],
        "provider_pool_count": inf_health["provider_pool_count"],
        "eligible_providers": inf_health["eligible_providers"],
        "knowledge_version": KNOWLEDGE_VERSION,
        "knowledge_chunks_count": len(CANONICAL_CHUNKS)
    }

@router.post("/chat")
def support_ai_chat(payload: ChatRequest, request: Request):
    """
    Public & Authenticated customer chat endpoint.
    Processes user query, enforces safety, executes hybrid RAG, and returns grounded response.
    """
    client_ip = get_client_ip(request)
    user_session = resolve_server_user_session(request)

    res = SupportAIService.handle_message(
        user_message=payload.message,
        session_id=payload.session_id,
        ecosystem=payload.ecosystem or "PLATFORM",
        module=payload.module or "General",
        user_session=user_session,
        client_ip=client_ip
    )
    return res

@router.post("/ticket/draft")
def support_ai_ticket_draft(payload: TicketDraftRequest, request: Request):
    """Create a draft support ticket from conversation context."""
    client_ip = get_client_ip(request)
    user_session = resolve_server_user_session(request)

    draft_res = ToolDispatcher.execute_tool(
        "create_support_ticket_draft",
        {
            "subject": payload.subject,
            "category": payload.category,
            "summary": payload.summary,
            "steps_attempted": payload.steps_attempted or ""
        },
        user_session=user_session,
        client_ip=client_ip
    )
    return draft_res

@router.post("/ticket/confirm")
def support_ai_ticket_confirm(payload: TicketConfirmRequest, request: Request):
    """Submit a confirmed support ticket into PostgreSQL and trigger admin notification."""
    client_ip = get_client_ip(request)
    user_session = resolve_server_user_session(request)

    submit_res = ToolDispatcher.execute_tool(
        "submit_support_ticket_after_confirmation",
        {
            "draft_id": payload.draft_id,
            "requester_name": payload.requester_name,
            "requester_email": payload.requester_email
        },
        user_session=user_session,
        client_ip=client_ip
    )
    return submit_res

@router.get("/tickets/mine")
def support_ai_my_tickets(request: Request):
    """Authenticated user's own support tickets history."""
    client_ip = get_client_ip(request)
    user_session = resolve_server_user_session(request)

    if not user_session:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Login diperlukan untuk melihat riwayat tiket Anda."}
        )

    res = ToolDispatcher.execute_tool(
        "list_own_support_tickets",
        {},
        user_session=user_session,
        client_ip=client_ip
    )
    return res

@router.get("/status")
def support_ai_public_status():
    """Live public platform status probe data."""
    return ToolDispatcher.execute_tool("get_public_platform_status", {})
