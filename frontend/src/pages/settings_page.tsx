import { useState } from "react";
import { supabase } from "../lib/supabase_client";

const SESSION_STORAGE_KEY = "copefy_session_id";

function SettingsPage() {
  const [loading, set_loading] = useState(false);

  const handle_logout = async () => {
    set_loading(true);
    try {
      await supabase.auth.signOut();
      localStorage.removeItem(SESSION_STORAGE_KEY);
      // ProtectedRoute redirects to /login once the auth state clears.
    } catch (error) {
      console.error("Failed to sign out:", error);
      set_loading(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center border-b border-slate-200 bg-white px-6 py-3">
        <span className="text-sm font-semibold text-slate-800">Settings</span>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-2xl">
          <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 className="text-base font-semibold text-slate-900">Account</h2>
            <p className="mt-1 text-sm text-slate-500">
              Sign out of your Copefy account on this device.
            </p>
            <button
              type="button"
              onClick={handle_logout}
              disabled={loading}
              className="mt-4 rounded-full bg-red-600 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Signing out..." : "Log Out"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
