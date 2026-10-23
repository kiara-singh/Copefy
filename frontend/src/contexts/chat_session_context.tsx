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
  /** Drop a dead local session id and switch to a real empty/new chat. */
  recover_session: () => Promise<string>;
}

const ChatSessionContext = createContext<ChatSessionContextValue | undefined>(
  undefined
);

function is_known_session(rows: SessionSummary[], id: string | null): boolean {
  return Boolean(id && rows.some((row) => row.session_id === id));
}

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

  const clear_session = useCallback(() => {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    set_session_id(null);
  }, []);

  const refresh_sessions = useCallback(async () => {
    try {
      const rows = await list_sessions();
      set_sessions(rows);
      return rows;
    } catch (error) {
      console.error("Failed to load chat history", error);
      return null;
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

  const open_fresh_session = useCallback(
    async (rows: SessionSummary[]) => {
      const empty = rows.find((row) => row.message_count === 0);
      if (empty) {
        persist_session(empty.session_id);
        return empty.session_id;
      }
      const new_id = await create_session();
      set_sessions((prev) => [
        {
          session_id: new_id,
          title: "New chat",
          last_activity: null,
          message_count: 0,
        },
        ...prev.filter((row) => row.session_id !== new_id),
      ]);
      persist_session(new_id);
      return new_id;
    },
    [persist_session]
  );

  const start_new_chat = useCallback(async () => {
    await open_fresh_session(sessions);
  }, [open_fresh_session, sessions]);

  const recover_session = useCallback(async () => {
    clear_session();
    const rows = (await refresh_sessions()) ?? [];
    return open_fresh_session(rows);
  }, [clear_session, open_fresh_session, refresh_sessions]);

  useEffect(() => {
    let cancelled = false;

    const boot = async () => {
      const rows = await list_sessions().catch((error) => {
        console.error("Failed to load chat history", error);
        return [] as SessionSummary[];
      });
      if (cancelled) {
        return;
      }

      set_sessions(rows);
      set_loading_list(false);

      const stored = localStorage.getItem(SESSION_STORAGE_KEY);
      if (is_known_session(rows, stored)) {
        set_session_id(stored);
        return;
      }

      // Stale localStorage id (deleted chat, other account, etc.): replace it.
      if (stored) {
        localStorage.removeItem(SESSION_STORAGE_KEY);
      }
      try {
        await open_fresh_session(rows);
      } catch (error) {
        console.error("Failed to create a chat session", error);
      }
    };

    void boot();

    return () => {
      cancelled = true;
    };
  }, [open_fresh_session]);

  return (
    <ChatSessionContext.Provider
      value={{
        session_id,
        sessions,
        loading_list,
        select_session,
        start_new_chat,
        refresh_sessions: async () => {
          await refresh_sessions();
        },
        recover_session,
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
