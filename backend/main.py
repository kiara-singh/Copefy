import asyncio
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from agent.orchestrator import run_agent
from config import settings
from db import get_supabase
from debug_trace import debug_log

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


class DebugRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # region agent log
        debug_log(
            "main.py:middleware",
            "request_received",
            data={"method": request.method, "path": request.url.path},
            hypothesis_id="H-A",
        )
        # endregion
        started = time.perf_counter()
        response = await call_next(request)
        # region agent log
        debug_log(
            "main.py:middleware",
            "request_completed",
            data={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            },
            hypothesis_id="H-A",
        )
        # endregion
        return response


app.add_middleware(DebugRequestMiddleware)


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


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Copefy API is running."}


@app.get("/health")
def health() -> dict[str, str]:
    # region agent log
    debug_log("main.py:health", "health_ok", hypothesis_id="H-A")
    # endregion
    return {"status": "ok"}


@app.post("/session")
def create_session() -> dict[str, str]:
    """Create a new chat session and return its id."""
    client = _require_supabase()
    session_id = str(uuid.uuid4())

    client.table("sessions").insert(
        {"id": session_id, "user_id": DEV_USER_ID}
    ).execute()

    return {"session_id": session_id}


@app.post("/chat")
async def chat(payload: ChatRequest) -> dict:
    """Store the user message, run the agent, and return the reply."""
    logger.info("chat start session=%s", payload.session_id)
    # region agent log
    debug_log(
        "main.py:chat",
        "chat_start",
        data={"session_id": payload.session_id, "msg_len": len(payload.message)},
        hypothesis_id="H-A",
    )
    # endregion
    client = _require_supabase()

    await asyncio.to_thread(
        _insert_message, client, payload.session_id, "user", payload.message
    )
    # region agent log
    debug_log("main.py:chat", "after_user_insert", hypothesis_id="H-C")
    # endregion
    history = await asyncio.to_thread(_load_session_history, client, payload.session_id)
    # region agent log
    debug_log(
        "main.py:chat",
        "after_load_history",
        data={"history_len": len(history)},
        hypothesis_id="H-C",
    )
    # endregion

    try:
        # region agent log
        debug_log("main.py:chat", "before_run_agent", hypothesis_id="H-F")
        # endregion
        result = await asyncio.wait_for(
            run_agent(
                payload.message,
                user_id=DEV_USER_ID,
                history=history[:-1],
            ),
            timeout=90.0,
        )
        # region agent log
        debug_log(
            "main.py:chat",
            "after_run_agent",
            data={"kb_used": result.kb_used},
            hypothesis_id="H-F",
        )
        # endregion
    except asyncio.TimeoutError as exc:
        # region agent log
        debug_log("main.py:chat", "chat_timeout", hypothesis_id="H-E")
        # endregion
        logger.warning("chat timeout session=%s", payload.session_id)
        raise HTTPException(
            status_code=504,
            detail="Response took too long. Please try again.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        from google.genai.errors import ClientError

        # region agent log
        debug_log(
            "main.py:chat",
            "chat_exception",
            data={"type": type(exc).__name__},
            hypothesis_id="H-E",
        )
        # endregion
        logger.exception("chat failed session=%s", payload.session_id)
        if isinstance(exc, ClientError) and exc.code == 429:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The AI service hit its free-tier limit for today. "
                    "Wait a bit and try again, or switch GEMINI_CHAT_MODEL "
                    "to gemini-flash-latest in backend/.env."
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
        "chat done session=%s kb_used=%s",
        payload.session_id,
        result.kb_used,
    )

    body: dict = {"response": result.response}
    if payload.debug or settings.rag_debug:
        body["trace"] = result.to_debug_dict()
    # region agent log
    debug_log("main.py:chat", "chat_done", hypothesis_id="H-A")
    # endregion
    return body


@app.post("/journal")
def create_journal_entry(payload: JournalRequest) -> dict[str, str]:
    """Store a raw journal entry. Vector embeddings are skipped for now."""
    client = _require_supabase()

    client.table("journal_entries").insert(
        {"user_id": DEV_USER_ID, "content": payload.text}
    ).execute()

    return {"status": "success"}
