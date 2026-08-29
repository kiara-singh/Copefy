import asyncio
import logging
import time
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from agent.orchestrator import run_agent
from config import settings
from db import get_supabase
from debug_trace import debug_log

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
def create_session(
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Create a new chat session for the authenticated user and return its id."""
    client = _require_supabase()
    session_id = str(uuid.uuid4())

    client.table("sessions").insert(
        {"id": session_id, "user_id": user_id}
    ).execute()

    return {"session_id": session_id}


@app.post("/chat")
async def chat(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Store the user message, run the agent, and return the reply."""
    logger.info("chat start session=%s user_id=%s", payload.session_id, user_id)
    # region agent log
    debug_log(
        "main.py:chat",
        "chat_start",
        data={"session_id": payload.session_id, "user_id": user_id, "msg_len": len(payload.message)},
        hypothesis_id="H-A",
    )
    # endregion
    client = _require_supabase()

    # Verify session ownership
    session_res = (
        client.table("sessions")
        .select("user_id")
        .eq("id", payload.session_id)
        .execute()
    )

    if not session_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    session_owner = str(session_res.data[0]["user_id"])
    if session_owner != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own this chat session.",
        )

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
                user_id=user_id,
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
async def create_journal_entry(
    payload: JournalRequest,
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Store a raw journal entry for the authenticated user and ingest its chunks for RAG retrieval."""
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
