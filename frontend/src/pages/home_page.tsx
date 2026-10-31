import { useEffect, useRef, useState } from "react";
import ChatTracePanel from "../components/chat_trace_panel";
import {
  create_session,
  get_personas,
  is_rag_debug_enabled,
  send_chat,
  type ChatSource,
  type ChatTrace,
  type AIPersona,
} from "../lib/api";

const SESSION_STORAGE_KEY = "copefy_session_id";
const PERSONA_STORAGE_KEY = "copefy_active_persona_id";

type ChatRole = "user" | "assistant";

interface ChatMessage {
  role: ChatRole;
  content: string;
  sources?: ChatSource[];
  trace?: ChatTrace;
}

function HomePage() {
  const [session_id, set_session_id] = useState<string | null>(null);
  const [messages, set_messages] = useState<ChatMessage[]>([]);
  const [input, set_input] = useState("");
  const [is_sending, set_is_sending] = useState(false);
  const [personas, set_personas] = useState<AIPersona[]>([]);
  const [selected_persona_id, set_selected_persona_id] = useState("");
  const scroll_anchor_ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const existing = localStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) {
      set_session_id(existing);
      return;
    }

    create_session()
      .then((new_id) => {
        localStorage.setItem(SESSION_STORAGE_KEY, new_id);
        set_session_id(new_id);
      })
      .catch((error) => {
        console.error("Failed to create a chat session", error);
      });
  }, []);

  useEffect(() => {
    get_personas()
      .then((available) => {
        set_personas(available);
        const saved = localStorage.getItem(PERSONA_STORAGE_KEY) ?? "";
        if (available.some((persona) => persona.id === saved)) {
          set_selected_persona_id(saved);
        } else {
          localStorage.removeItem(PERSONA_STORAGE_KEY);
        }
      })
      .catch((error) => {
        console.error("Failed to load personas", error);
      });
  }, []);

  useEffect(() => {
    scroll_anchor_ref.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || !session_id || is_sending) {
      return;
    }

    set_messages((prev) => [...prev, { role: "user", content: trimmed }]);
    set_input("");
    set_is_sending(true);

    try {
      const data = await send_chat(
        session_id,
        trimmed,
        selected_persona_id || null
      );
      set_messages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          sources: data.sources,
          trace: data.trace,
        },
      ]);
    } catch (error) {
      console.error("Failed to send message", error);
      const message =
        error instanceof Error
          ? error.message
          : "Sorry, something went wrong. Please try again.";
      set_messages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: message,
        },
      ]);
    } finally {
      set_is_sending(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <span className="text-sm font-semibold text-slate-800">Chat</span>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <span>Persona</span>
            <select
              aria-label="Active chat persona"
              value={selected_persona_id}
              onChange={(event) => {
                const id = event.target.value;
                set_selected_persona_id(id);
                if (id) {
                  localStorage.setItem(PERSONA_STORAGE_KEY, id);
                } else {
                  localStorage.removeItem(PERSONA_STORAGE_KEY);
                }
              }}
              disabled={is_sending}
              className="max-w-52 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:opacity-60"
            >
              <option value="">Default Copefy</option>
              {personas.map((persona) => (
                <option key={persona.id} value={persona.id}>
                  {persona.name} · {persona.role_type}
                </option>
              ))}
            </select>
          </label>
          {is_rag_debug_enabled && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              Trace on
            </span>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.length === 0 ? (
            <div className="mt-24 text-center text-slate-400">
              <p className="text-lg font-medium">How are you feeling today?</p>
              <p className="mt-1 text-sm">
                Start the conversation whenever you're ready.
              </p>
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={index}>
                <div
                  className={`flex ${
                    message.role === "user" ? "justify-end" : "justify-start"
                  }`}
                >
                  <div
                    className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
                      message.role === "user"
                        ? "bg-indigo-600 text-white"
                        : "bg-white text-slate-800 shadow-sm ring-1 ring-slate-200"
                    }`}
                  >
                    {message.content}
                  </div>
                </div>
                {message.role === "assistant" && message.sources?.length ? (
                  <div className="mt-2 max-w-[80%] rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                    <p className="mb-1 font-medium text-slate-700">Sources</p>
                    <ul className="space-y-1">
                      {message.sources.map((source, sourceIndex) => (
                        <li key={`${source.source_url ?? "source"}-${sourceIndex}`}>
                          {source.source_url ? (
                            <a
                              href={source.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-indigo-600 underline hover:text-indigo-800"
                            >
                              {source.title ?? source.source_url}
                            </a>
                          ) : (
                            source.title ?? `Source ${sourceIndex + 1}`
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {message.role === "assistant" && message.trace && (
                  <ChatTracePanel trace={message.trace} />
                )}
              </div>
            ))
          )}
          {is_sending && (
            <div className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl bg-white px-4 py-2 text-sm text-slate-400 shadow-sm ring-1 ring-slate-200">
                Typing...
              </div>
            </div>
          )}
          <div ref={scroll_anchor_ref} />
        </div>
      </div>

      <div className="sticky bottom-0 border-t border-slate-200 bg-white px-6 py-4">
        <form
          onSubmit={handle_submit}
          className="mx-auto flex max-w-2xl items-center gap-2"
        >
          <button
            type="button"
            aria-label="Voice input (coming soon)"
            title="Voice input coming soon"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-5 w-5"
            >
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>

          <input
            type="text"
            value={input}
            onChange={(event) => set_input(event.target.value)}
            placeholder="Type your message..."
            className="flex-1 rounded-full border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />

          <button
            type="submit"
            disabled={!input.trim() || !session_id || is_sending}
            className="shrink-0 rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

export default HomePage;
