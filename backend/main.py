import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from db import get_supabase


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


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Copefy API is running."}


@app.get("/health")
def health() -> dict[str, str]:
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
def chat(payload: ChatRequest) -> dict[str, str]:
    """Store the user message, generate a placeholder AI reply, and return it."""
    client = _require_supabase()

    client.table("messages").insert(
        {
            "session_id": payload.session_id,
            "role": "user",
            "content": payload.message,
        }
    ).execute()

    # Hardcoded default response until the RAG / LLM pipeline is wired up.
    reply = (
        "Thanks for sharing that with me. I'm here to listen. "
        "Can you tell me a little more about how that's making you feel?"
    )

    client.table("messages").insert(
        {
            "session_id": payload.session_id,
            "role": "assistant",
            "content": reply,
        }
    ).execute()

    return {"response": reply}


@app.post("/journal")
def create_journal_entry(payload: JournalRequest) -> dict[str, str]:
    """Store a raw journal entry. Vector embeddings are skipped for now."""
    client = _require_supabase()

    client.table("journal_entries").insert(
        {"user_id": DEV_USER_ID, "content": payload.text}
    ).execute()

    return {"status": "success"}
