import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { IncidentCard } from "../components/IncidentCard";
import { PullRequestCard } from "../components/PullRequestCard";
import { ResolvedCard } from "../components/ResolvedCard";
import type { Incident } from "../types/incident";

type Health = { status: string; mode: string; region: string };

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [items, h] = await Promise.all([api.listIncidents(), api.health()]);
      setIncidents(items);
      setHealth(h);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reach the API");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const handleVerify = useCallback(
    async (id: string) => {
      setVerifyingId(id);
      try {
        await api.verify(id);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Verification failed");
      } finally {
        setVerifyingId(null);
      }
    },
    [load]
  );

  const active = incidents.filter((i) => i.status === "PENDING" || i.status === "DIAGNOSING");
  const openPrs = incidents.filter(
    (i) => (i.status === "PR_OPEN" || i.status === "DEPLOYING") && i.pull_request
  );
  const resolved = incidents.filter((i) => i.status === "RESOLVED_VERIFIED");

  return (
    <div className="app">
      <header className="header">
        <div className="header__brand">
          <div className="header__logo">A</div>
          <div>
            <h1 className="header__title">AgentSentry AI</h1>
            <p className="header__subtitle">
              Autonomous remediation copilot · every fix proven, every call read-only
            </p>
          </div>
        </div>
        {health && (
          <span className={`badge badge--${health.mode}`}>
            {health.mode.toUpperCase()} · {health.region}
          </span>
        )}
      </header>

      {error && <div className="error">⚠ {error}</div>}

      <div className="board">
        <section className="column">
          <div className="column__head">
            <span className="column__title">Active Incidents</span>
            <span className="column__count">{active.length}</span>
          </div>
          {active.length === 0 && <div className="empty">No active incidents</div>}
          {active.map((inc) => (
            <IncidentCard key={inc.id} incident={inc} />
          ))}
        </section>

        <section className="column">
          <div className="column__head">
            <span className="column__title">Open PRs</span>
            <span className="column__count">{openPrs.length}</span>
          </div>
          {openPrs.length === 0 && <div className="empty">No remediation PRs open</div>}
          {openPrs.map((inc) => (
            <PullRequestCard
              key={inc.id}
              incident={inc}
              onVerify={handleVerify}
              verifying={verifyingId === inc.id}
            />
          ))}
        </section>

        <section className="column">
          <div className="column__head">
            <span className="column__title">Verified Resolutions</span>
            <span className="column__count">{resolved.length}</span>
          </div>
          {resolved.length === 0 && <div className="empty">No verified resolutions yet</div>}
          {resolved.map((inc) => (
            <ResolvedCard key={inc.id} incident={inc} />
          ))}
        </section>
      </div>
    </div>
  );
}
