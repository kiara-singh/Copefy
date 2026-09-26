import { useEffect, useRef, useState } from "react";
import ChatTracePanel from "../components/chat_trace_panel";
import { useChatSession } from "../contexts/chat_session_context";
import {
  get_session_messages,
  is_rag_debug_enabled,
  send_chat,
  type ChatTrace,
} from "../lib/api";

type ChatRole = "user" | "assistant";

interface ChatMessage {
  role: ChatRole;
  content: string;
  trace?: ChatTrace;
}

function get_speech_recognition(): SpeechRecognition | null {
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Ctor) {
    return null;
  }
  return new Ctor();
}

function HomePage() {
  const { session_id, sessions, loading_list, refresh_sessions } =
    useChatSession();
  const [messages, set_messages] = useState<ChatMessage[]>([]);
  const [input, set_input] = useState("");
  const [is_sending, set_is_sending] = useState(false);
  const [loading_history, set_loading_history] = useState(false);
  const [is_listening, set_is_listening] = useState(false);
  const [speech_supported, set_speech_supported] = useState(true);
  const [speech_error, set_speech_error] = useState("");
  const scroll_anchor_ref = useRef<HTMLDivElement | null>(null);
  const sessions_ref = useRef(sessions);
  const recognition_ref = useRef<SpeechRecognition | null>(null);
  const want_listening_ref = useRef(false);
  const base_input_ref = useRef("");
  sessions_ref.current = sessions;

  useEffect(() => {
    set_speech_supported(
      Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
    );
  }, []);

  useEffect(() => {
    return () => {
      want_listening_ref.current = false;
      recognition_ref.current?.abort();
      recognition_ref.current = null;
    };
  }, []);

  useEffect(() => {
    if (!session_id) {
      set_messages([]);
      set_loading_history(false);
      return;
    }

    if (loading_list) {
      const known = sessions_ref.current.find(
        (row) => row.session_id === session_id
      );
      if (known?.message_count === 0) {
        set_messages([]);
        set_loading_history(false);
        return;
      }
      set_loading_history(true);
      return;
    }

    const message_count = sessions_ref.current.find(
      (row) => row.session_id === session_id
    )?.message_count;

    if (message_count === 0) {
      set_messages([]);
      set_loading_history(false);
      return;
    }

    let cancelled = false;
    set_loading_history(true);
    set_messages([]);

    get_session_messages(session_id)
      .then((rows) => {
        if (cancelled) {
          return;
        }
        set_messages(
          rows.map((row) => ({
            role: row.role,
            content: row.content,
          }))
        );
      })
      .catch((error) => {
        console.error("Failed to load chat messages", error);
      })
      .finally(() => {
        if (!cancelled) {
          set_loading_history(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [session_id, loading_list]);

  useEffect(() => {
    scroll_anchor_ref.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const stop_listening = () => {
    want_listening_ref.current = false;
    recognition_ref.current?.stop();
  };

  const speech_error_message = (code: string): string => {
    switch (code) {
      case "not-allowed":
        return "Microphone permission is blocked. Allow it in the browser, then try again.";
      case "audio-capture":
        return "No microphone found. Plug one in or check system settings.";
      case "network":
        return "Voice input needs a network connection (browser speech service). Check your connection and try again.";
      case "service-not-allowed":
        return "Voice input is blocked in this browser. Try Chrome or Edge.";
      case "language-not-supported":
        return "This language is not supported for voice input. Try typing instead.";
      default:
        return "Voice input failed. You can keep typing instead.";
    }
  };

  const toggle_listening = () => {
    if (is_sending) {
      return;
    }

    if (is_listening || want_listening_ref.current) {
      stop_listening();
      set_is_listening(false);
      return;
    }

    if (typeof window !== "undefined" && !window.isSecureContext) {
      set_speech_error(
        "Voice input needs a secure page (https or localhost). Open the app via localhost."
      );
      return;
    }

    if (!speech_supported) {
      set_speech_error(
        "Voice input needs Chrome, Edge, or Safari. Type instead for now."
      );
      return;
    }

    const recognition = get_speech_recognition();
    if (!recognition) {
      set_speech_supported(false);
      set_speech_error(
        "Voice input needs Chrome, Edge, or Safari. Type instead for now."
      );
      return;
    }

    set_speech_error("");
    base_input_ref.current = input.trimEnd();
    recognition.continuous = true;
    recognition.interimResults = true;
    const lang =
      typeof navigator !== "undefined" && navigator.language
        ? navigator.language
        : "en-US";
    recognition.lang = lang.includes("-") ? lang : "en-US";

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let final_chunk = "";
      let interim_chunk = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const piece = result[0]?.transcript ?? "";
        if (result.isFinal) {
          final_chunk += piece;
        } else {
          interim_chunk += piece;
        }
      }
      if (final_chunk) {
        const prefix = base_input_ref.current;
        base_input_ref.current =
          `${prefix}${prefix ? " " : ""}${final_chunk.trim()}`.trim();
      }
      const draft = `${base_input_ref.current}${
        interim_chunk
          ? `${base_input_ref.current ? " " : ""}${interim_chunk.trim()}`
          : ""
      }`.trimStart();
      set_input(draft);
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // Chrome ends a session with no-speech after silence; onend restarts
      // while the user still wants to listen.
      if (event.error === "aborted" || event.error === "no-speech") {
        return;
      }
      want_listening_ref.current = false;
      set_speech_error(speech_error_message(event.error));
      set_is_listening(false);
      recognition_ref.current = null;
    };

    recognition.onend = () => {
      if (want_listening_ref.current && recognition_ref.current === recognition) {
        try {
          recognition.start();
          return;
        } catch (error) {
          console.error("Failed to restart speech recognition", error);
          want_listening_ref.current = false;
          set_speech_error("Voice input failed. You can keep typing instead.");
        }
      }
      set_is_listening(false);
      if (recognition_ref.current === recognition) {
        recognition_ref.current = null;
      }
      set_input((current) => current.trim());
    };

    try {
      want_listening_ref.current = true;
      recognition_ref.current = recognition;
      recognition.start();
      set_is_listening(true);
    } catch (error) {
      console.error("Failed to start speech recognition", error);
      want_listening_ref.current = false;
      set_speech_error("Voice input failed. You can keep typing instead.");
      set_is_listening(false);
      recognition_ref.current = null;
    }
  };

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || !session_id || is_sending) {
      return;
    }

    if (is_listening || want_listening_ref.current) {
      stop_listening();
      set_is_listening(false);
    }

    const is_first_message = messages.length === 0;
    set_messages((prev) => [...prev, { role: "user", content: trimmed }]);
    set_input("");
    set_is_sending(true);
    set_speech_error("");

    try {
      const data = await send_chat(session_id, trimmed);
      set_messages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          trace: data.trace,
        },
      ]);
      if (is_first_message) {
        void refresh_sessions();
      }
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

  const show_empty = !loading_history && messages.length === 0;
  const mic_title = !speech_supported
    ? "Voice input unavailable in this browser"
    : is_listening
      ? "Stop listening"
      : "Start voice input";

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <span className="text-sm font-semibold text-slate-800">Chat</span>
        {is_rag_debug_enabled && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            Trace on
          </span>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {loading_history ? (
            <div className="mt-24 text-center text-sm text-slate-400">
              Loading conversation…
            </div>
          ) : show_empty ? (
            <div className="mt-24 text-center text-slate-400">
              <p className="text-lg font-medium">How are you feeling today?</p>
              <p className="mt-1 text-sm">
                Type a message or tap the mic to talk.
              </p>
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={`${message.role}-${index}`}>
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
                {is_rag_debug_enabled && message.trace && (
                  <ChatTracePanel trace={message.trace} />
                )}
              </div>
            ))
          )}
          {is_sending && (
            <div className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl bg-white px-4 py-2 text-sm text-slate-400 shadow-sm ring-1 ring-slate-200">
                Thinking…
              </div>
            </div>
          )}
          <div ref={scroll_anchor_ref} />
        </div>
      </div>

      <div className="sticky bottom-0 border-t border-slate-200 bg-white px-6 py-4">
        <form
          onSubmit={handle_submit}
          className="mx-auto flex max-w-2xl flex-col gap-2"
        >
          {speech_error && (
            <p className="px-1 text-xs text-red-600">{speech_error}</p>
          )}
          {is_listening && !speech_error && (
            <p className="px-1 text-xs text-indigo-600">Listening… tap mic to stop</p>
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={mic_title}
              title={mic_title}
              aria-pressed={is_listening}
              disabled={is_sending}
              onClick={toggle_listening}
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                is_listening
                  ? "bg-red-100 text-red-600 hover:bg-red-200"
                  : "text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              }`}
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
              onChange={(event) => {
                const value = event.target.value;
                set_input(value);
                if (want_listening_ref.current) {
                  base_input_ref.current = value.trimEnd();
                }
              }}
              placeholder={
                is_listening ? "Listening…" : "Type your message..."
              }
              className="flex-1 rounded-full border border-slate-300 px-4 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />

            <button
              type="submit"
              disabled={!input.trim() || !session_id || is_sending}
              className="shrink-0 rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default HomePage;
