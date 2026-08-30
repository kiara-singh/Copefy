import asyncio
import logging
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.orchestrator import run_agent
from auth import resolve_user_id
from config import settings
from db import get_supabase
from profiles import load_user_persona

logger = logging.getLogger(__name__)

DEV_USER_ID = "78b0cc86-0b60-4220-8127-4430b1f3cd9e"

app = FastAPI(
    title="Copefy API",
    description="Backend for Copefy, an AI mental health and wellness companion.",
    version="0.0.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    debug: bool = Field(
        default=False,
        description="If true, include KB retrieval trace in the response.",
    )


class JournalRequest(BaseModel):
    text: str


def _require_supabase():
    """Return the Supabase client or raise a 503 if it is not configured."""
    client = get_supabase()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY.",
        )
    return client


def _insert_message(client, session_id: str, role: str, content: str) -> None:
    client.table("messages").insert(
        {"session_id": session_id, "role": role, "content": content}
    ).execute()


def _load_session_history(client, session_id: str) -> list[dict[str, str]]:
    result = (
        client.table("messages")
        .select("role, content")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    return [{"role": row["role"], "content": row["content"]} for row in result.data]


def _get_session_user_id(client, session_id: str) -> str:
    result = (
        client.table("sessions")
        .select("user_id")
        .eq("id", session_id)
        .maybe_single()
        .execute()
    )
    if result.data and result.data.get("user_id"):
        return str(result.data["user_id"])
    return DEV_USER_ID


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Copefy API is running."}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/session")
def create_session(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Create a new chat session and return its id."""
    client = _require_supabase()
    user_id = resolve_user_id(authorization, fallback_user_id=DEV_USER_ID)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please log in again. Your session could not be verified.",
        )

    session_id = str(uuid.uuid4())

    try:
        client.table("sessions").insert(
            {"id": session_id, "user_id": user_id}
        ).execute()
    except Exception as exc:
        from postgrest.exceptions import APIError

        if isinstance(exc, APIError) and exc.code == "23503":
            raise HTTPException(
                status_code=401,
                detail=(
                    "Could not create a chat session for this account. "
                    "Try logging out and back in."
                ),
            ) from exc
        raise

    return {"session_id": session_id}


@app.post("/chat")
async def chat(
    payload: ChatRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    """Store the user message, run the agent, and return the reply."""
    logger.info("chat start session=%s", payload.session_id)
    client = _require_supabase()

    session_user_id = await asyncio.to_thread(
        _get_session_user_id, client, payload.session_id
    )
    auth_user_id = resolve_user_id(authorization, fallback_user_id=None)
    user_id = auth_user_id or session_user_id
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please log in again. Your session could not be verified.",
        )
    persona = await asyncio.to_thread(load_user_persona, user_id)

    await asyncio.to_thread(
        _insert_message, client, payload.session_id, "user", payload.message
    )
    history = await asyncio.to_thread(_load_session_history, client, payload.session_id)

    try:
        result = await asyncio.wait_for(
            run_agent(
                payload.message,
                user_id=user_id,
                history=history[:-1],
                persona=persona,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("chat timeout session=%s", payload.session_id)
        raise HTTPException(
            status_code=504,
            detail="Response took too long. Please try again.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        from google.genai.errors import APIError

        logger.exception("chat failed session=%s", payload.session_id)
        if isinstance(exc, APIError):
            if exc.code == 429:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "The AI service hit its rate limit. "
                        "Wait a moment and try again."
                    ),
                ) from exc
            if exc.code in {500, 502, 503, 504}:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "The AI service is temporarily busy. "
                        "We tried several models — please try again in a minute."
                    ),
                ) from exc
        raise HTTPException(
            status_code=500,
            detail="Failed to generate a response. Please try again.",
        ) from exc

    await asyncio.to_thread(
        _insert_message, client, payload.session_id, "assistant", result.response
    )
    logger.info(
        "chat done session=%s kb_used=%s style=%s",
        payload.session_id,
        result.kb_used,
        result.communication_style,
    )

    body: dict = {"response": result.response}
    if payload.debug or settings.rag_debug:
        body["trace"] = result.to_debug_dict()
    return body


@app.post("/journal")
def create_journal_entry(
    payload: JournalRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Store a raw journal entry. Vector embeddings are skipped for now."""
    client = _require_supabase()
    user_id = resolve_user_id(authorization, fallback_user_id=DEV_USER_ID)

    client.table("journal_entries").insert(
        {"user_id": user_id, "content": payload.text}
    ).execute()

    return {"status": "success"}
