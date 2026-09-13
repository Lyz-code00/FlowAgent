import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { clearToken, getToken } from "./api";
import Shell from "./components/Shell";
import Configuration from "./pages/Configuration";
import Conversations from "./pages/Conversations";
import Dashboard from "./pages/Dashboard";
import Feedback from "./pages/Feedback";
import Knowledge from "./pages/Knowledge";
import Login from "./pages/Login";
import Summaries from "./pages/Summaries";
import Users from "./pages/Users";

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getToken()));
  useEffect(() => {
    const unauthorized = () => setAuthenticated(false);
    window.addEventListener("flowagent:unauthorized", unauthorized);
    return () => window.removeEventListener("flowagent:unauthorized", unauthorized);
  }, []);

  if (!authenticated) return <Login onSuccess={() => setAuthenticated(true)} />;
  return (
    <Shell onLogout={() => { clearToken(); setAuthenticated(false); }}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/conversations" element={<Conversations />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/users" element={<Users />} />
        <Route path="/summaries" element={<Summaries />} />
        <Route path="/feedback" element={<Feedback />} />
        <Route path="/configuration" element={<Configuration />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
