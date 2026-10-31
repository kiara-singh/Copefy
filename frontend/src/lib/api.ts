import { supabase } from "./supabase_client";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 120_000;
const RAG_DEBUG = import.meta.env.VITE_RAG_DEBUG === "true";

export interface ChatSource {
  title: string | null;
  source_url: string | null;
  category: string | null;
  similarity?: number;
  preview?: string;
  excerpt?: string;
}

export interface PipelineLayer {
  layer: number;
  name: string;
  decision: string;
  ms: number;
  router?: string;
  reason?: string;
  strategy?: string;
  search_query?: string;
  categories?: string[];
  candidates?: number;
  returned?: number;
  top_similarity?: number;
  sources?: ChatSource[];
  communication_style?: string;
  preferred_name_set?: boolean;
  wellness_goal_set?: boolean;
  coaching_preferences_set?: boolean;
  structured_format_requested?: boolean;
  model?: string;
  history_turns?: number;
  kb_chunks_in_prompt?: number;
  anti_repeat?: boolean;
}

export interface PipelineTrace {
  total_ms: number;
  layers: PipelineLayer[];
}

export interface ChatTrace {
  path: string;
  router: string;
  route_reason: string;
  tools_used: string[];
  kb_used: boolean;
  search_query: string | null;
  categories: string[];
  model: string | null;
  tool_status: string | null;
  chunk_count: number;
  sources: ChatSource[];
  communication_style?: string;
  pipeline?: PipelineTrace;
}

export interface ChatResponse {
  response: string;
  sources?: ChatSource[];
  trace?: ChatTrace;
}

export interface AIPersona {
  id: string;
  user_id: string;
  name: string;
  role_type: string;
  base_personality: string;
  custom_instructions: string;
  avatar_preference?: unknown;
  created_at: string;
}

export interface PersonaPayload {
  name: string;
  role_type: string;
  base_personality: string;
  custom_instructions: string;
}

export interface MedicalDocument {
  id: string;
  user_id: string;
  file_name: string;
  storage_url: string;
  uploaded_at: string;
}

async function auth_headers(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function api_request<T>(
  path: string,
  method: string = "GET",
  body?: unknown
): Promise<T> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;

  const headers: Record<string, string> = {};
  let req_body: BodyInit | undefined = undefined;

  if (body !== undefined) {
    if (body instanceof FormData) {
      req_body = body;
    } else {
      headers["Content-Type"] = "application/json";
      req_body = JSON.stringify(body);
    }
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: req_body,
      signal: controller.signal,
    });

    if (!response.ok) {
      let error_message = `Request to ${path} failed with status ${response.status}`;
      try {
        const err_json = (await response.json()) as { detail?: string };
        if (err_json && err_json.detail) {
          error_message =
            typeof err_json.detail === "string"
              ? err_json.detail
              : JSON.stringify(err_json.detail);
        }
      } catch {}
      throw new Error(error_message);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(
        "Request timed out. The server may still be thinking — try again."
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function post_json<T>(path: string, body: unknown): Promise<T> {
  return await api_request<T>(path, "POST", body);
}

export async function create_session(): Promise<string> {
  const data = await api_request<{ session_id: string }>("/session", "POST", {});
  return data.session_id;
}

export async function send_chat(
  session_id: string,
  message: string,
  persona_id?: string | null
): Promise<ChatResponse> {
  return await api_request<ChatResponse>("/chat", "POST", {
    session_id,
    message,
    persona_id: persona_id ?? null,
    debug: RAG_DEBUG,
  });
}

export async function submit_journal(text: string): Promise<void> {
  await api_request<{ status: string }>("/journal", "POST", { text });
}

export async function get_personas(): Promise<AIPersona[]> {
  return await api_request<AIPersona[]>("/personas", "GET");
}

export async function create_persona(
  payload: PersonaPayload
): Promise<AIPersona> {
  return await api_request<AIPersona>("/personas", "POST", payload);
}

export async function update_persona(
  id: string,
  payload: PersonaPayload
): Promise<AIPersona> {
  return await api_request<AIPersona>(`/personas/${id}`, "PUT", payload);
}

export async function delete_persona(id: string): Promise<void> {
  await api_request<{ status: string }>(`/personas/${id}`, "DELETE");
}

export async function get_medical_documents(): Promise<MedicalDocument[]> {
  return await api_request<MedicalDocument[]>("/medical-documents", "GET");
}

export async function upload_medical_document(
  file: File
): Promise<MedicalDocument> {
  const formData = new FormData();
  formData.append("file", file);
  return await api_request<MedicalDocument>(
    "/medical-documents",
    "POST",
    formData
  );
}

export async function delete_medical_document(id: string): Promise<void> {
  await api_request<{ status: string }>(`/medical-documents/${id}`, "DELETE");
}

export const is_rag_debug_enabled = RAG_DEBUG;
