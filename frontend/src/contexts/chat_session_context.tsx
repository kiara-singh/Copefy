import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  create_session,
  list_sessions,
  type SessionSummary,
} from "../lib/api";

export const SESSION_STORAGE_KEY = "copefy_session_id";

interface ChatSessionContextValue {
  session_id: string | null;
  sessions: SessionSummary[];
  loading_list: boolean;
  select_session: (id: string) => void;
  start_new_chat: () => Promise<void>;
  refresh_sessions: () => Promise<void>;
}

const ChatSessionContext = createContext<ChatSessionContextValue | undefined>(
  undefined
);

export function ChatSessionProvider({ children }: { children: ReactNode }) {
  const [session_id, set_session_id] = useState<string | null>(() =>
    localStorage.getItem(SESSION_STORAGE_KEY)
  );
  const [sessions, set_sessions] = useState<SessionSummary[]>([]);
  const [loading_list, set_loading_list] = useState(true);

  const persist_session = useCallback((id: string) => {
    localStorage.setItem(SESSION_STORAGE_KEY, id);
    set_session_id(id);
  }, []);

  const refresh_sessions = useCallback(async () => {
    try {
      const rows = await list_sessions();
      set_sessions(rows);
    } catch (error) {
      console.error("Failed to load chat history", error);
    } finally {
      set_loading_list(false);
    }
  }, []);

  const select_session = useCallback(
    (id: string) => {
      persist_session(id);
    },
    [persist_session]
  );

  const start_new_chat = useCallback(async () => {
    const empty = sessions.find((row) => row.message_count === 0);
    if (empty) {
      persist_session(empty.session_id);
      return;
    }
    const new_id = await create_session();
    set_sessions((prev) => [
      {
        session_id: new_id,
        title: "New chat",
        last_activity: null,
        message_count: 0,
      },
      ...prev,
    ]);
    persist_session(new_id);
  }, [persist_session, sessions]);

  useEffect(() => {
    let cancelled = false;

    const ensure_session = async () => {
      const existing = localStorage.getItem(SESSION_STORAGE_KEY);
      if (existing) {
        if (!cancelled) {
          set_session_id(existing);
        }
        return;
      }
      try {
        const new_id = await create_session();
        if (!cancelled) {
          persist_session(new_id);
        }
      } catch (error) {
        console.error("Failed to create a chat session", error);
      }
    };

    void ensure_session().then(() => {
      if (!cancelled) {
        return refresh_sessions();
      }
    });

    return () => {
      cancelled = true;
    };
  }, [persist_session, refresh_sessions]);

  return (
    <ChatSessionContext.Provider
      value={{
        session_id,
        sessions,
        loading_list,
        select_session,
        start_new_chat,
        refresh_sessions,
      }}
    >
      {children}
    </ChatSessionContext.Provider>
  );
}

export function useChatSession() {
  const value = useContext(ChatSessionContext);
  if (!value) {
    throw new Error("useChatSession must be used within ChatSessionProvider");
  }
  return value;
}
