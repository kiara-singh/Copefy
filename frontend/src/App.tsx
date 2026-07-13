import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/app_layout";
import HomePage from "./pages/home_page";
import JournalPage from "./pages/journal_page";

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default App;
