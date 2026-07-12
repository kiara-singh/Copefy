import { Outlet } from "react-router-dom";
import Sidebar from "./sidebar";

function AppLayout() {
  return (
    <div className="flex h-screen bg-slate-50 text-slate-900">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}

export default AppLayout;
