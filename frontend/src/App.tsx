import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/app_layout";
import HomePage from "./pages/home_page";
import JournalPage from "./pages/journal_page";
import LoginPage from "./pages/login_page";
import OnboardingPage from "./pages/onboarding_page";
import SettingsPage from "./pages/settings_page";
import { ProtectedRoute } from "./components/protected_route";
import { PublicRoute } from "./components/public_route";

function App() {
  return (
    <Routes>
      {/* Public Routes */}
      <Route element={<PublicRoute />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>

      {/* Protected Routes */}
      <Route element={<ProtectedRoute />}>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/journal" element={<JournalPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}

export default App;
