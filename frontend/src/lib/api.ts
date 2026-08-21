import { supabase } from "./supabase_client";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

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

  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: req_body,
  });

  if (!response.ok) {
    let error_message = `Request to ${path} failed with status ${response.status}`;
    try {
      const err_json = await response.json();
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
}

export async function create_session(): Promise<string> {
  const data = await api_request<{ session_id: string }>("/session", "POST", {});
  return data.session_id;
}

export async function send_chat(
  session_id: string,
  message: string
): Promise<string> {
  const data = await api_request<{ response: string }>("/chat", "POST", {
    session_id,
    message,
  });
  return data.response;
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
