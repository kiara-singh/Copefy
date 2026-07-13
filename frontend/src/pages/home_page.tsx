import { useEffect, useRef, useState } from "react";
import { create_session, send_chat } from "../lib/api";
import { supabase } from "../lib/supabase_client";

const SESSION_STORAGE_KEY = "copefy_session_id";

type ChatRole = "user" | "assistant";

interface ChatMessage {
  role: ChatRole;
  content: string;
}

function HomePage() {
  const [session_id, set_session_id] = useState<string | null>(null);
  const [messages, set_messages] = useState<ChatMessage[]>([]);
  const [input, set_input] = useState("");
  const [is_sending, set_is_sending] = useState(false);
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
    scroll_anchor_ref.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handle_logout = async () => {
    try {
      await supabase.auth.signOut();
      localStorage.removeItem(SESSION_STORAGE_KEY);
      set_session_id(null);
      set_messages([]);
    } catch (error) {
      console.error("Failed to sign out:", error);
    }
  };

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
      const reply = await send_chat(session_id, trimmed);
      set_messages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (error) {
      console.error("Failed to send message", error);
      set_messages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
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
        <button
          onClick={handle_logout}
          className="flex items-center justify-center h-8 px-4 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 hover:text-slate-800 text-xs font-semibold leading-none transition-colors"
        >Sign Out</button>
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
              <div
                key={index}
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
