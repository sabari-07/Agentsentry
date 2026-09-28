import React, { useCallback, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { Dashboard } from "./pages/Dashboard";
import { Judges } from "./pages/Judges";
import "./styles/global.css";

/**
 * Minimal hash routing so the reviewers' tour has a shareable URL
 * (`...amazonaws.com/#judges`) without pulling in a router dependency.
 */
function App() {
  const [hash, setHash] = useState(() => window.location.hash);

  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const goDashboard = useCallback(() => {
    window.location.hash = "";
  }, []);

  if (hash.replace("#", "").toLowerCase() === "judges") {
    return <Judges onExit={goDashboard} />;
  }
  return <Dashboard />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
