import uuid

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from config import settings
from db import get_supabase

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
    """Create a new chat session for the authenticated user and return its id."""
    client = _require_supabase()
    session_id = str(uuid.uuid4())

    client.table("sessions").insert(
        {"id": session_id, "user_id": user_id}
    ).execute()

    return {"session_id": session_id}


@app.post("/chat")
def chat(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Store the user message for an owned session, generate a placeholder AI reply, and return it."""
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

    session_owner = session_res.data[0]["user_id"]
    if str(session_owner) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not own this chat session.",
        )

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
def create_journal_entry(
    payload: JournalRequest,
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Store a raw journal entry for the authenticated user. Vector embeddings are skipped for now."""
    client = _require_supabase()

    client.table("journal_entries").insert(
        {"user_id": user_id, "content": payload.text}
    ).execute()

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



