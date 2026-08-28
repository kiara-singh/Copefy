const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 120_000;
const RAG_DEBUG = import.meta.env.VITE_RAG_DEBUG === "true";

export interface ChatSource {
  title: string | null;
  source_url: string | null;
  category: string | null;
  similarity: number;
  excerpt: string;
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
}

export interface ChatResponse {
  response: string;
  trace?: ChatTrace;
}

async function post_json<T>(path: string, body: unknown): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
