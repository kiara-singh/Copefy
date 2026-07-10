import { Link, Navigate, Route, Routes } from "react-router-dom";
import HomePage from "./pages/home_page";
import LoginPage from "./pages/login_page";
import SettingsPage from "./pages/settings_page";

function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <nav className="flex gap-6 border-b border-slate-200 bg-white px-6 py-4 text-sm font-medium">
        <Link to="/" className="hover:text-indigo-600">
          Home
        </Link>
        <Link to="/login" className="hover:text-indigo-600">
          Login / Sign Up
        </Link>
        <Link to="/settings" className="hover:text-indigo-600">
          Settings
        </Link>
      </nav>

      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
