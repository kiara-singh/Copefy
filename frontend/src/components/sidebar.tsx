import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useChatSession } from "../contexts/chat_session_context";

const SIDEBAR_COLLAPSED_KEY = "copefy_sidebar_collapsed";

const journal_icon = (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    className="h-5 w-5 shrink-0"
  >
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
  </svg>
);

const settings_icon = (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    className="h-5 w-5 shrink-0"
  >
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06-.06a2 2 0 1 1-2.83-2.83l-.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06-.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l.06-.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const plus_icon = (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    className="h-5 w-5 shrink-0"
  >
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </svg>
);

const personas_icon = (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.75"
    strokeLinecap="round"
    strokeLinejoin="round"
    className="h-5 w-5 shrink-0"
  >
    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);

function Sidebar() {
  const navigate = useNavigate();
  const { session_id, sessions, loading_list, select_session, start_new_chat } =
    useChatSession();
  const [collapsed, set_collapsed] = useState(
    () => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true"
  );
  const [creating, set_creating] = useState(false);

  const toggle_collapsed = () => {
    set_collapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      return next;
    });
  };

  const nav_link_class = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
      collapsed ? "justify-center" : ""
    } ${
      isActive
        ? "bg-indigo-50 text-indigo-700"
        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
    }`;

  const visible_sessions = sessions.filter(
    (row) => row.message_count > 0 || row.session_id === session_id
  );

  const already_on_empty_chat = sessions.some(
    (row) => row.session_id === session_id && row.message_count === 0
  );

  const handle_new_chat = async () => {
    if (already_on_empty_chat) {
      navigate("/");
      return;
    }
    if (creating || loading_list) {
      return;
    }
    set_creating(true);
    try {
      await start_new_chat();
      navigate("/");
    } catch (error) {
      console.error("Failed to start a new chat", error);
    } finally {
      set_creating(false);
    }
  };

  const handle_select_chat = (id: string) => {
    select_session(id);
    navigate("/");
  };

  return (
    <aside
      className={`flex ${
        collapsed ? "w-16" : "w-64"
      } shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200`}
    >
      <div
        className={`flex h-[68px] items-center px-3 ${
          collapsed ? "justify-center" : "justify-between"
        }`}
      >
        {!collapsed && (
          <span className="pl-2 text-xl font-bold tracking-tight text-indigo-600">
            Copefy
          </span>
        )}
        <button
          type="button"
          onClick={toggle_collapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800"
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
            {collapsed ? (
              <path d="M9 18l6-6-6-6" />
            ) : (
              <path d="M15 18l-6-6 6-6" />
            )}
          </svg>
        </button>
      </div>

      <div className="flex flex-1 flex-col gap-1 overflow-hidden px-3">
        <button
          type="button"
          onClick={() => void handle_new_chat()}
          disabled={creating}
          title="New chat"
          aria-label="New chat"
          className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50 ${
            collapsed ? "justify-center" : ""
          }`}
        >
          {plus_icon}
          {!collapsed && <span>{creating ? "Starting…" : "New chat"}</span>}
        </button>

        {!collapsed && (
          <div className="mt-2 flex min-h-0 flex-1 flex-col">
            <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              History
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {loading_list ? (
                <p className="px-3 py-2 text-xs text-slate-400">Loading…</p>
              ) : visible_sessions.length === 0 ? (
                <p className="px-3 py-2 text-xs text-slate-400">
                  No chats yet
                </p>
              ) : (
                visible_sessions.map((row) => {
                  const active = row.session_id === session_id;
                  return (
                    <button
                      key={row.session_id}
                      type="button"
                      onClick={() => handle_select_chat(row.session_id)}
                      title={row.title}
                      className={`mb-0.5 w-full truncate rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                        active
                          ? "bg-indigo-50 font-medium text-indigo-700"
                          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                      }`}
                    >
                      {row.title}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        )}

        <NavLink
          to="/journal"
          className={nav_link_class}
          title={collapsed ? "Journal Entries" : undefined}
        >
          {journal_icon}
          {!collapsed && <span>Journal Entries</span>}
        </NavLink>

        <NavLink
          to="/personas"
          className={nav_link_class}
          title={collapsed ? "Personas" : undefined}
        >
          {personas_icon}
          {!collapsed && <span>Personas</span>}
        </NavLink>
      </div>

      <div className="border-t border-slate-200 px-3 py-4">
        <NavLink
          to="/settings"
          className={nav_link_class}
          title={collapsed ? "Settings" : undefined}
        >
          {settings_icon}
          {!collapsed && <span>Settings</span>}
        </NavLink>
      </div>
    </aside>
  );
}

export default Sidebar;
