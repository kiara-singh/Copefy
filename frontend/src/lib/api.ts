import { supabase } from "./supabase_client";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 120_000;
const RAG_DEBUG = import.meta.env.VITE_RAG_DEBUG === "true";

export interface ChatSource {
  title: string | null;
  source_url: string | null;
  category: string | null;
  similarity: number;
  preview: string;
  excerpt: string;
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
  trace?: ChatTrace;
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

async function post_json<T>(path: string, body: unknown): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const headers = await auth_headers();
    const response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = `Request to ${path} failed with status ${response.status}`;
      try {
        const error_body = (await response.json()) as { detail?: string };
        if (error_body.detail) {
          detail = error_body.detail;
        }
      } catch {
        // ignore JSON parse errors on error responses
      }
      throw new Error(detail);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Request timed out. The server may still be thinking — try again.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function create_session(): Promise<string> {
  const data = await post_json<{ session_id: string }>("/session", {});
  return data.session_id;
}

export async function send_chat(
  session_id: string,
  message: string
): Promise<ChatResponse> {
  return post_json<ChatResponse>("/chat", {
    session_id,
    message,
    debug: RAG_DEBUG,
  });
}

export async function submit_journal(text: string): Promise<void> {
  await post_json<{ status: string }>("/journal", { text });
}

export const is_rag_debug_enabled = RAG_DEBUG;
