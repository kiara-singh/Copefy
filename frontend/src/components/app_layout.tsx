import { Outlet } from "react-router-dom";
import { ChatSessionProvider } from "../contexts/chat_session_context";
import Sidebar from "./sidebar";

function AppLayout() {
  return (
    <ChatSessionProvider>
      <div className="flex h-screen bg-slate-50 text-slate-900">
        <Sidebar />
        <main className="flex flex-1 flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
    </ChatSessionProvider>
  );
}

export default AppLayout;
