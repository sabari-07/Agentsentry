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
  IconLogo,
  IconPR,
  IconShield,
} from "../components/icons";
import type { Incident } from "../types/incident";
import { money } from "../utils/format";

type Health = { status: string; mode: string; region: string };
type View = "all" | "incidents" | "prs" | "verifications" | "audit";

const NAV: { id: View; label: string; group: string }[] = [
  { id: "all", label: "Overview", group: "Operations" },
  { id: "incidents", label: "Incidents", group: "Operations" },
  { id: "prs", label: "Pull requests", group: "Operations" },
  { id: "verifications", label: "Verifications", group: "Operations" },
  { id: "audit", label: "Read-only audit", group: "Governance" },
];

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [view, setView] = useState<View>("all");

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
  const withAudit = incidents.filter((i) => i.audit_calls.length > 0);

  const savings = [...resolved, ...openPrs].reduce((sum, i) => {
    const c = i.pull_request?.cost_delta;
    return c ? sum + (c.after_monthly_usd - c.before_monthly_usd) : sum;
  }, 0);

  // Which columns to show for the selected view.
  const show = {
    incidents: view === "all" || view === "incidents",
    prs: view === "all" || view === "prs",
    resolved: view === "all" || view === "verifications",
    audit: view === "audit",
  };

  const groups = [...new Set(NAV.map((n) => n.group))];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__logo">
            <IconLogo size={22} />
          </div>
          <div>
            <div className="brand__name">AgentSentry AI</div>
            <div className="brand__tag">Remediation agent</div>
          </div>
        </div>

        <nav className="nav">
          {groups.map((g) => (
            <div key={g}>
              <div className="nav__label" style={{ marginTop: g === groups[0] ? 0 : 18 }}>
                {g}
              </div>
              {NAV.filter((n) => n.group === g).map((n) => (
                <button
                  key={n.id}
                  className={`nav__item ${view === n.id ? "nav__item--active" : ""}`}
                  onClick={() => setView(n.id)}
                >
                  <span className="nav__dot" /> {n.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <main className="main">
        <div className="topbar">
          <div>
            <h1 className="topbar__title">
              {view === "all"
                ? "Incident Operations"
                : NAV.find((n) => n.id === view)?.label}
            </h1>
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

        {/* KPI stats — clickable to filter the board */}
        <div className="stats">
          <button
            className="stat"
            style={{ ["--accent" as string]: "var(--red)" }}
            onClick={() => setView("incidents")}
          >
            <div className="stat__label">
              <IconActivity size={13} /> Active incidents
            </div>
            <div className="stat__value">{active.length}</div>
            <div className="stat__hint">detecting &amp; diagnosing</div>
          </button>
          <button
            className="stat"
            style={{ ["--accent" as string]: "var(--amber)" }}
            onClick={() => setView("prs")}
          >
            <div className="stat__label">
              <IconPR size={13} /> Awaiting review
            </div>
            <div className="stat__value">{openPrs.length}</div>
            <div className="stat__hint">remediation PRs open</div>
          </button>
          <button
            className="stat"
            style={{ ["--accent" as string]: "var(--green)" }}
            onClick={() => setView("verifications")}
          >
            <div className="stat__label">
              <IconCheck size={13} /> Verified fixes
            </div>
            <div className="stat__value">{resolved.length}</div>
            <div className="stat__hint">metric confirmed healthy</div>
          </button>
          <button
            className="stat"
            style={{ ["--accent" as string]: "var(--brand)" }}
            onClick={() => setView("audit")}
          >
            <div className="stat__label">
              <IconShield size={13} /> Cost impact / mo
            </div>
            <div className="stat__value">{money(savings)}</div>
            <div className="stat__hint">across proposed fixes</div>
          </button>
        </div>

        {/* Audit view: flat list of incidents with their read-only audit trails */}
        {show.audit && (
          <section className="column" style={{ maxWidth: 720 }}>
            <div className="column__head">
              <span
                className="column__icon"
                style={{ background: "rgba(91,140,255,0.15)", color: "var(--brand)" }}
              >
                <IconShield size={14} />
              </span>
              <span className="column__title">Read-only Audit Trail</span>
              <span className="column__count">{withAudit.length}</span>
            </div>
            {loading && <div className="skeleton skeleton-card" />}
            {!loading && withAudit.length === 0 && (
              <div className="empty">No audited agent activity yet</div>
            )}
            {withAudit.map((inc) =>
              inc.status === "RESOLVED_VERIFIED" ? (
                <ResolvedCard key={inc.id} incident={inc} />
              ) : inc.pull_request ? (
                <PullRequestCard
                  key={inc.id}
                  incident={inc}
                  onVerify={handleVerify}
                  verifying={verifyingId === inc.id}
                />
              ) : (
                <IncidentCard key={inc.id} incident={inc} />
              )
            )}
          </section>
        )}

        {/* Board — columns adapt to the selected view */}
        {!show.audit && (
          <div
            className="board"
            style={{
              gridTemplateColumns:
                [show.incidents, show.prs, show.resolved].filter(Boolean).length === 1
                  ? "minmax(0, 720px)"
                  : undefined,
            }}
          >
            {show.incidents && (
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
                {!loading && active.length === 0 && (
                  <div className="empty">No active incidents</div>
                )}
                {active.map((inc) => (
                  <IncidentCard key={inc.id} incident={inc} />
                ))}
              </section>
            )}

            {show.prs && (
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
            )}

            {show.resolved && (
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
            )}
          </div>
        )}
      </main>
    </div>
  );
}
