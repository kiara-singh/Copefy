import asyncio
import logging
import uuid

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from agent.orchestrator import run_agent
from auth import resolve_user_id
from chat_history import summarize_sessions
from config import settings
from db import get_supabase
from profiles import load_user_persona

logger = logging.getLogger(__name__)

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

security = HTTPBearer()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    debug: bool = Field(
        default=False,
        description=(
            "If true, include a metadata-only retrieval trace. Never includes "
            "raw journal or clinical snippet text."
        ),
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


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Validate Supabase Bearer token and return the authenticated user's UUID."""
    client = _require_supabase()
    token = credentials.credentials
    try:
        user_res = client.auth.get_user(token)
        if not user_res or not user_res.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token.",
            )
        return str(user_res.user.id)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(err)}",
        )


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


def _require_session_access(
    client,
    session_id: str,
    auth_user_id: str | None,
) -> str:
    """Return the session owner, or 404 if missing / not owned by the caller."""
    result = (
        client.table("sessions")
        .select("user_id")
        .eq("id", session_id)
        .maybe_single()
        .execute()
    )
    # supabase-py maybe_single() returns None (not {data: None}) when 0 rows.
    row = getattr(result, "data", None)
    if not row or not row.get("user_id"):
        raise HTTPException(status_code=404, detail="Chat not found.")
    owner_id = str(row["user_id"])
    if auth_user_id and auth_user_id != owner_id:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return owner_id


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Copefy API is running."}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/session")
def create_session(
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Create a new chat session and return its id."""
    client = _require_supabase()
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


@app.get("/sessions")
def list_sessions(
    authorization: str | None = Header(default=None),
) -> dict:
    """List this user's chats, newest first, with a title from the first user message."""
    client = _require_supabase()
    user_id = resolve_user_id(authorization, fallback_user_id=None)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please log in again. Your session could not be verified.",
        )

    sessions_result = (
        client.table("sessions")
        .select("id, started_at")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(80)
        .execute()
    )
    sessions = sessions_result.data or []
    if not sessions:
        return {"sessions": []}

    session_ids = [row["id"] for row in sessions]
    messages_result = (
        client.table("messages")
        .select("session_id, role, content, created_at")
        .in_("session_id", session_ids)
        .order("created_at")
        .execute()
    )
    return {
        "sessions": summarize_sessions(sessions, messages_result.data or []),
    }


@app.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    """Load messages for one chat owned by the logged-in user."""
    client = _require_supabase()
    auth_user_id = resolve_user_id(authorization, fallback_user_id=None)
    if not auth_user_id:
        raise HTTPException(
            status_code=401,
            detail="Please log in again. Your session could not be verified.",
        )
    _require_session_access(client, session_id, auth_user_id)
    result = (
        client.table("messages")
        .select("role, content, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    messages = [
        {
            "role": row["role"],
            "content": row["content"],
            "created_at": row.get("created_at"),
        }
        for row in (result.data or [])
        if row.get("role") in {"user", "assistant"}
    ]
    return {"session_id": session_id, "messages": messages}


@app.post("/chat")
async def chat(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Store the user message, run the agent, and return the reply."""
    logger.info("chat start session=%s user_id=%s", payload.session_id, user_id)
    client = _require_supabase()
    await asyncio.to_thread(
        _require_session_access, client, payload.session_id, user_id
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
    # Client debug and server RAG_DEBUG may attach metadata. Raw retrieved
    # text never leaves this HTTP response.
    if payload.debug or settings.rag_debug:
        body["trace"] = result.to_public_debug_dict()
    return body


@app.post("/journal")
async def create_journal_entry(
    payload: JournalRequest,
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Store a raw journal entry and ingest its chunks for RAG retrieval."""
    client = _require_supabase()

    res = (
        client.table("journal_entries")
        .insert({"user_id": user_id, "content": payload.text})
        .execute()
    )

    if res.data:
        journal_id = str(res.data[0]["id"])
        try:
            from rag.journal_ingestion import ingest_journal_entry

            await ingest_journal_entry(journal_id, user_id, payload.text)
        except Exception as err:
            logger.warning(
                "Journal ingestion failed for entry %s: %s", journal_id, err
            )

    return {"status": "success"}


@app.post("/journal/audio")
async def create_audio_journal_entry(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """Upload private audio, transcribe it, and ingest the transcript as a text journal."""
    from rag.audio_journal import AudioJournalError, ingest_audio_journal

    client = _require_supabase()
    filename = file.filename or "journal.wav"
    contents = await file.read()
    try:
        return await ingest_audio_journal(
            client,
            user_id,
            filename,
            file.content_type,
            contents,
        )
    except AudioJournalError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err)) from err


@app.post("/journal/video")
async def create_video_journal_entry(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """Upload private video, extract audio locally, transcribe, ingest as text journal."""
    from rag.media_journal import MediaJournalError
    from rag.video_journal import ingest_video_journal

    client = _require_supabase()
    filename = file.filename or "journal.mp4"
    contents = await file.read()
    try:
        return await ingest_video_journal(
            client,
            user_id,
            filename,
            file.content_type,
            contents,
        )
    except MediaJournalError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err)) from err


class PersonaPayload(BaseModel):
    name: str
    role_type: str
    base_personality: str
    custom_instructions: str


@app.get("/personas")
def get_personas(user_id: str = Depends(get_current_user)):
    """Retrieve all AI persona configurations owned by the authenticated user."""
    client = _require_supabase()
    res = (
        client.table("ai_personas")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


@app.post("/personas")
def create_persona(
    payload: PersonaPayload,
    user_id: str = Depends(get_current_user),
):
    """Create a new AI persona configuration for the authenticated user."""
    name = payload.name.strip()
    role_type = payload.role_type.strip()
    base_personality = payload.base_personality.strip()
    custom_instructions = payload.custom_instructions.strip()

    if not name or not role_type or not base_personality:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name, role_type, and base_personality cannot be empty.",
        )

    client = _require_supabase()
    res = (
        client.table("ai_personas")
        .insert(
            {
                "user_id": user_id,
                "name": name,
                "role_type": role_type,
                "base_personality": base_personality,
                "custom_instructions": custom_instructions,
            }
        )
        .execute()
    )

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create persona.",
        )

    return res.data[0]


@app.put("/personas/{persona_id}")
def update_persona(
    persona_id: str,
    payload: PersonaPayload,
    user_id: str = Depends(get_current_user),
):
    """Update an existing AI persona configuration owned by the authenticated user."""
    name = payload.name.strip()
    role_type = payload.role_type.strip()
    base_personality = payload.base_personality.strip()
    custom_instructions = payload.custom_instructions.strip()

    if not name or not role_type or not base_personality:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name, role_type, and base_personality cannot be empty.",
        )

    client = _require_supabase()

    # Check persona ownership
    existing_res = (
        client.table("ai_personas")
        .select("user_id")
        .eq("id", persona_id)
        .execute()
    )

    if not existing_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found.",
        )

    if str(existing_res.data[0]["user_id"]) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own this persona.",
        )

    res = (
        client.table("ai_personas")
        .update(
            {
                "name": name,
                "role_type": role_type,
                "base_personality": base_personality,
                "custom_instructions": custom_instructions,
            }
        )
        .eq("id", persona_id)
        .execute()
    )

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update persona.",
        )

    return res.data[0]


@app.delete("/personas/{persona_id}")
def delete_persona(
    persona_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete an existing AI persona configuration owned by the authenticated user."""
    client = _require_supabase()

    # Check persona ownership
    existing_res = (
        client.table("ai_personas")
        .select("user_id")
        .eq("id", persona_id)
        .execute()
    )

    if not existing_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found.",
        )

    if str(existing_res.data[0]["user_id"]) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own this persona.",
        )

    client.table("ai_personas").delete().eq("id", persona_id).execute()

    return {"status": "success"}


MAX_MEDICAL_DOC_SIZE = 10 * 1024 * 1024  # 10 MB
MEDICAL_STORAGE_BUCKET = "medical-documents"


@app.get("/medical-documents")
def get_medical_documents(user_id: str = Depends(get_current_user)):
    """Retrieve metadata for all medical documents owned by the authenticated user."""
    client = _require_supabase()
    res = (
        client.table("medical_documents")
        .select("*")
        .eq("user_id", user_id)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return res.data or []


@app.post("/medical-documents")
async def upload_medical_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """Upload a PDF medical document to private Supabase Storage and record its metadata."""
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only PDF documents (.pdf) are supported.",
        )

    if file.content_type and file.content_type.lower() != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MIME type. Only PDF documents (application/pdf) are supported.",
        )

    contents = await file.read()
    if len(contents) > MAX_MEDICAL_DOC_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds the 10 MB maximum limit.",
        )

    if b"%PDF-" not in contents[:1024]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PDF file. The uploaded file does not contain a valid PDF header (%PDF-).",
        )

    client = _require_supabase()

    # Generate safe unique storage object path scoped to authenticated user UUID
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-").strip()
    storage_path = f"{user_id}/{uuid.uuid4()}_{safe_filename}"

    # Upload to private Supabase Storage bucket
    try:
        client.storage.from_(MEDICAL_STORAGE_BUCKET).upload(
            path=storage_path,
            file=contents,
            file_options={"content-type": "application/pdf"},
        )
    except Exception as err:
        err_msg = str(err)
        if "not_found" in err_msg.lower() or "bucket" in err_msg.lower():
            detail = "Storage bucket 'medical-documents' was not found in Supabase. Please create the private 'medical-documents' bucket in Supabase Dashboard."
        else:
            detail = f"Failed to upload document to private storage: {err_msg}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )

    # Record metadata in public.medical_documents table
    try:
        res = (
            client.table("medical_documents")
            .insert(
                {
                    "user_id": user_id,
                    "file_name": filename,
                    "storage_url": storage_path,
                }
            )
            .execute()
        )
        if not res.data:
            raise Exception("No data returned from database insert.")
    except Exception as err:
        # Cleanup orphaned storage object if database insert fails
        try:
            client.storage.from_(MEDICAL_STORAGE_BUCKET).remove([storage_path])
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record medical document metadata: {str(err)}",
        )

    return res.data[0]


@app.delete("/medical-documents/{document_id}")
def delete_medical_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete an existing medical document record and its underlying storage object."""
    client = _require_supabase()

    # Check document ownership
    existing_res = (
        client.table("medical_documents")
        .select("id, user_id, storage_url")
        .eq("id", document_id)
        .execute()
    )

    if not existing_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medical document not found.",
        )

    doc_record = existing_res.data[0]
    if str(doc_record["user_id"]) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own this medical document.",
        )

    storage_path = doc_record.get("storage_url")

    # Remove storage object if path exists
    if storage_path:
        try:
            client.storage.from_(MEDICAL_STORAGE_BUCKET).remove([storage_path])
        except Exception:
            pass

    client.table("medical_documents").delete().eq("id", document_id).execute()

    return {"status": "success"}
