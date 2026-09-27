import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { IncidentCard } from "../components/IncidentCard";
import { PullRequestCard } from "../components/PullRequestCard";
import { ResolvedCard } from "../components/ResolvedCard";
import {
  IconActivity,
  IconAlert,
  IconCheck,
  IconClock,
  IconPR,
  IconShield,
} from "../components/icons";
import type { Incident } from "../types/incident";
import { money } from "../utils/format";

type Health = { status: string; mode: string; region: string };

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [items, h] = await Promise.all([api.listIncidents(), api.health()]);
      setIncidents(items);
      setHealth(h);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reach the API");
    } finally {
      setLoading(false);
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

  // Total monthly cost impact across resolved + open PRs.
  const savings = [...resolved, ...openPrs].reduce((sum, i) => {
    const c = i.pull_request?.cost_delta;
    return c ? sum + (c.after_monthly_usd - c.before_monthly_usd) : sum;
  }, 0);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__logo">A</div>
          <div>
            <div className="brand__name">AgentSentry AI</div>
            <div className="brand__tag">Remediation copilot</div>
          </div>
        </div>

        <nav className="nav">
          <div className="nav__label">Operations</div>
          <div className="nav__item nav__item--active">
            <span className="nav__dot" /> Incidents
          </div>
          <div className="nav__item">
            <span className="nav__dot" /> Pull requests
          </div>
          <div className="nav__item">
            <span className="nav__dot" /> Verifications
          </div>
          <div className="nav__label" style={{ marginTop: 18 }}>
            Governance
          </div>
          <div className="nav__item">
            <span className="nav__dot" /> Read-only audit
          </div>
        </nav>

        <div className="sidebar__footer">
          Read-only by construction.
          <br />
          Human-in-the-loop by design.
          <br />
          100% AWS Free Tier.
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div>
            <h1 className="topbar__title">Incident Operations</h1>
            <p className="topbar__subtitle">
              Autonomous detection, reviewable Infrastructure-as-Code remediation, and post-deploy
              verification — every fix proven, every agent call read-only.
            </p>
          </div>
          <div className="topbar__meta">
            {health && (
              <>
                <span className={`status status--${health.mode}`}>
                  <span className="status__dot" />
                  {health.mode === "live" ? "Live" : "Mock"}
                </span>
                <span className="chip">{health.region}</span>
              </>
            )}
          </div>
        </div>

        {error && (
          <div className="banner banner--error">
            <IconAlert size={16} /> {error}
          </div>
        )}

        {/* KPI stats */}
        <div className="stats">
          <div className="stat" style={{ ["--accent" as string]: "var(--red)" }}>
            <div className="stat__label">
              <IconActivity size={13} /> Active incidents
            </div>
            <div className="stat__value">{active.length}</div>
            <div className="stat__hint">detecting & diagnosing</div>
          </div>
          <div className="stat" style={{ ["--accent" as string]: "var(--amber)" }}>
            <div className="stat__label">
              <IconPR size={13} /> Awaiting review
            </div>
            <div className="stat__value">{openPrs.length}</div>
            <div className="stat__hint">remediation PRs open</div>
          </div>
          <div className="stat" style={{ ["--accent" as string]: "var(--green)" }}>
            <div className="stat__label">
              <IconCheck size={13} /> Verified fixes
            </div>
            <div className="stat__value">{resolved.length}</div>
            <div className="stat__hint">metric confirmed healthy</div>
          </div>
          <div className="stat" style={{ ["--accent" as string]: "var(--brand)" }}>
            <div className="stat__label">
              <IconShield size={13} /> Cost impact / mo
            </div>
            <div className="stat__value">{money(savings)}</div>
            <div className="stat__hint">across proposed fixes</div>
          </div>
        </div>

        {/* Board */}
        <div className="board">
          <section className="column">
            <div className="column__head">
              <span
                className="column__icon"
                style={{ background: "var(--red-dim)", color: "var(--red)" }}
              >
                <IconAlert size={14} />
              </span>
              <span className="column__title">Active Incidents</span>
              <span className="column__count">{active.length}</span>
            </div>
            {loading && <div className="skeleton skeleton-card" />}
            {!loading && active.length === 0 && <div className="empty">No active incidents</div>}
            {active.map((inc) => (
              <IncidentCard key={inc.id} incident={inc} />
            ))}
          </section>

          <section className="column">
            <div className="column__head">
              <span
                className="column__icon"
                style={{ background: "var(--amber-dim)", color: "var(--amber)" }}
              >
                <IconPR size={14} />
              </span>
              <span className="column__title">Open PRs</span>
              <span className="column__count">{openPrs.length}</span>
            </div>
            {loading && <div className="skeleton skeleton-card" />}
            {!loading && openPrs.length === 0 && (
              <div className="empty">No remediation PRs open</div>
            )}
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
              <span
                className="column__icon"
                style={{ background: "var(--green-dim)", color: "var(--green)" }}
              >
                <IconCheck size={14} />
              </span>
              <span className="column__title">Verified Resolutions</span>
              <span className="column__count">{resolved.length}</span>
            </div>
            {loading && <div className="skeleton skeleton-card" />}
            {!loading && resolved.length === 0 && (
              <div className="empty">
                <IconClock size={18} />
                <div style={{ marginTop: 8 }}>No verified resolutions yet</div>
              </div>
            )}
            {resolved.map((inc) => (
              <ResolvedCard key={inc.id} incident={inc} />
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}
