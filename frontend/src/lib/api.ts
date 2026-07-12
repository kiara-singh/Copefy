const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function post_json<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function create_session(): Promise<string> {
  const data = await post_json<{ session_id: string }>("/session", {});
  return data.session_id;
}

export async function send_chat(
  session_id: string,
  message: string
): Promise<string> {
  const data = await post_json<{ response: string }>("/chat", {
    session_id,
    message,
  });
  return data.response;
}

export async function submit_journal(text: string): Promise<void> {
  await post_json<{ status: string }>("/journal", { text });
}
