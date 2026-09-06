import os
import uuid
from datetime import datetime, timezone

import httpx
import psycopg
from psycopg.rows import dict_row

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


DATABASE_URL = os.environ["DATABASE_URL"]
SCHEMA = os.environ["AI_CHAT_SCHEMA"]
ORCHESTRATOR_URL = os.environ.get(
    "ORCHESTRATOR_URL",
    "http://127.0.0.1:18130",
)

app = FastAPI(
    title="BotConnector AI Chat Core",
    version="0.5.1",
)


def db():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
    )


def user_id(value: str | None):
    if not value:
        raise HTTPException(401, "missing identity")

    try:
        return uuid.UUID(value)
    except Exception:
        raise HTTPException(401, "invalid identity")


def qtable(name: str):
    return f'"{SCHEMA}"."{name}"'


class ConversationCreate(BaseModel):
    title: str | None = None


class RenameRequest(BaseModel):
    title: str


class MessageRequest(BaseModel):
    content: str
    mode: str = "fast"


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "botconnector-ai-chat-core",
        "version": "0.5.1",
        "persistence": "postgresql-isolated-candidate",
        "schema": SCHEMA,
        "orchestrator": ORCHESTRATOR_URL,
    }


@app.post("/v1/conversations")
def create_conversation(
    req: ConversationCreate,
    x_botconnector_user_id: str | None = Header(default=None),
):
    uid = user_id(x_botconnector_user_id)

    title = (req.title or "Percakapan baru").strip()
    if not title:
        title = "Percakapan baru"

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {qtable("conversations")}
                    (user_id,title)
                VALUES (%s,%s)
                RETURNING id,title,created_at,updated_at
                """,
                (uid, title),
            )
            row = cur.fetchone()

    return row


@app.get("/v1/conversations")
def list_conversations(
    x_botconnector_user_id: str | None = Header(default=None),
):
    uid = user_id(x_botconnector_user_id)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    (
                        SELECT count(*)
                        FROM {qtable("messages")} m
                        WHERE m.conversation_id=c.id
                    ) AS message_count
                FROM {qtable("conversations")} c
                WHERE c.user_id=%s
                ORDER BY c.updated_at DESC
                """,
                (uid,),
            )
            return cur.fetchall()


@app.get("/v1/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    x_botconnector_user_id: str | None = Header(default=None),
):
    uid = user_id(x_botconnector_user_id)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id,title,created_at,updated_at
                FROM {qtable("conversations")}
                WHERE id=%s AND user_id=%s
                """,
                (conversation_id, uid),
            )
            conversation = cur.fetchone()

            if not conversation:
                raise HTTPException(404, "conversation not found")

            cur.execute(
                f"""
                SELECT
                    id,
                    role,
                    content,
                    provider,
                    model,
                    created_at
                FROM {qtable("messages")}
                WHERE conversation_id=%s
                ORDER BY created_at,id
                """,
                (conversation_id,),
            )

            messages = cur.fetchall()

    return {
        **conversation,
        "messages": messages,
    }


@app.patch("/v1/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: uuid.UUID,
    req: RenameRequest,
    x_botconnector_user_id: str | None = Header(default=None),
):
    uid = user_id(x_botconnector_user_id)

    title = req.title.strip()
    if not title:
        raise HTTPException(400, "empty title")

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {qtable("conversations")}
                SET title=%s,
                    updated_at=now()
                WHERE id=%s
                  AND user_id=%s
                RETURNING id,title
                """,
                (title, conversation_id, uid),
            )

            row = cur.fetchone()

    if not row:
        raise HTTPException(404, "conversation not found")

    return {
        "ok": True,
        **row,
    }


@app.delete("/v1/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: uuid.UUID,
    x_botconnector_user_id: str | None = Header(default=None),
):
    uid = user_id(x_botconnector_user_id)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                DELETE FROM {qtable("conversations")}
                WHERE id=%s
                  AND user_id=%s
                RETURNING id
                """,
                (conversation_id, uid),
            )

            row = cur.fetchone()

    if not row:
        raise HTTPException(404, "conversation not found")

    return {"ok": True}


@app.post("/v1/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    req: MessageRequest,
    x_botconnector_user_id: str | None = Header(default=None),
):
    uid = user_id(x_botconnector_user_id)

    content = req.content.strip()
    if not content:
        raise HTTPException(400, "empty message")

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id,title
                FROM {qtable("conversations")}
                WHERE id=%s
                  AND user_id=%s
                """,
                (conversation_id, uid),
            )

            conversation = cur.fetchone()

            if not conversation:
                raise HTTPException(404, "conversation not found")

            cur.execute(
                f"""
                SELECT role,content
                FROM {qtable("messages")}
                WHERE conversation_id=%s
                ORDER BY created_at,id
                """,
                (conversation_id,),
            )

            history = cur.fetchall()

    messages = [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in history
        if row["role"] in ("user", "assistant")
    ]

    messages.append({
        "role": "user",
        "content": content,
    })

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            ORCHESTRATOR_URL + "/v1/chat",
            json={
                "messages": messages,
                "task": req.mode,
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            502,
            "orchestrator request failed",
        )

    result = response.json()

    assistant_content = (
        result.get("content")
        or result.get("text")
        or result.get("message")
    )

    if isinstance(assistant_content, dict):
        assistant_content = assistant_content.get("content")

    if not assistant_content:
        raise HTTPException(
            502,
            "orchestrator returned no content",
        )

    provider = result.get("provider")
    model = result.get("model")

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {qtable("messages")}
                    (conversation_id,role,content)
                VALUES (%s,'user',%s)
                RETURNING id,role,content,created_at
                """,
                (conversation_id, content),
            )
            user_message = cur.fetchone()

            cur.execute(
                f"""
                INSERT INTO {qtable("messages")}
                    (
                        conversation_id,
                        role,
                        content,
                        provider,
                        model
                    )
                VALUES (%s,'assistant',%s,%s,%s)
                RETURNING
                    id,
                    role,
                    content,
                    provider,
                    model,
                    created_at
                """,
                (
                    conversation_id,
                    assistant_content,
                    provider,
                    model,
                ),
            )
            assistant_message = cur.fetchone()

            if (
                conversation["title"] == "Percakapan baru"
                and len(history) == 0
            ):
                auto_title = content[:80]

                cur.execute(
                    f"""
                    UPDATE {qtable("conversations")}
                    SET title=%s,
                        updated_at=now()
                    WHERE id=%s
                    """,
                    (auto_title, conversation_id),
                )
            else:
                cur.execute(
                    f"""
                    UPDATE {qtable("conversations")}
                    SET updated_at=now()
                    WHERE id=%s
                    """,
                    (conversation_id,),
                )

    return {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "mode": req.mode,
        "provider": provider,
        "model": model,
    }
