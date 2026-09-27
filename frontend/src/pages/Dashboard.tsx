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
  IconDollar,
  IconLogo,
  IconPR,
  IconShield,
} from "../components/icons";
import type { Incident } from "../types/incident";
import { money } from "../utils/format";

type Health = { status: string; mode: string; region: string };
type View = "overview" | "incidents" | "prs" | "verifications" | "audit";

const NAV: { id: View; label: string; group: string; icon: JSX.Element }[] = [
  { id: "overview", label: "Overview", group: "Operations", icon: <IconActivity size={16} /> },
  { id: "incidents", label: "Incidents", group: "Operations", icon: <IconAlert size={16} /> },
  { id: "prs", label: "Pull requests", group: "Operations", icon: <IconPR size={16} /> },
  { id: "verifications", label: "Verifications", group: "Operations", icon: <IconCheck size={16} /> },
  { id: "audit", label: "Read-only audit", group: "Governance", icon: <IconShield size={16} /> },
];

const TITLES: Record<View, { title: string; sub: string }> = {
  overview: {
    title: "Overview",
    sub: "Live snapshot of autonomous detection, reviewable remediation, and verified fixes.",
  },
  incidents: {
    title: "Incidents",
    sub: "Every detected infrastructure incident and its current diagnosis state.",
  },
  prs: {
    title: "Pull Requests",
    sub: "Merge-ready Infrastructure-as-Code remediations with cost delta, diff, and rollback.",
  },
  verifications: {
    title: "Verifications",
    sub: "Fixes confirmed by re-checking the live metric after deploy — proof, not claims.",
  },
  audit: {
    title: "Read-only Audit",
    sub: "CloudTrail evidence that every agent action was read-only (Describe / Get / List).",
  },
};

export function Dashboard() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [view, setView] = useState<View>("overview");

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

  const meta = TITLES[view];
  const groups = [...new Set(NAV.map((n) => n.group))];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__logo">
            <IconLogo size={23} />
          </div>
          <div>
            <div className="brand__name">AgentSentry AI</div>
            <div className="brand__tag">Remediation agent</div>
          </div>
        </div>

        <nav className="nav">
          {groups.map((g, gi) => (
            <div key={g}>
              <div className="nav__label" style={{ marginTop: gi === 0 ? 0 : 20 }}>
                {g}
              </div>
              {NAV.filter((n) => n.group === g).map((n) => (
                <button
                  key={n.id}
                  className={`nav__item ${view === n.id ? "nav__item--active" : ""}`}
                  onClick={() => setView(n.id)}
                >
                  <span className="nav__ic">{n.icon}</span>
                  {n.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <main className="main">
        <div className="topbar">
          <div>
            <h1 className="topbar__title">{meta.title}</h1>
            <p className="topbar__subtitle">{meta.sub}</p>
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

        {/* ---------------- OVERVIEW ---------------- */}
        {view === "overview" && (
          <>
            <div className="stats">
              <StatCard
                icon={<IconAlert size={17} />}
                tint="var(--red)"
                bg="var(--red-dim)"
                value={active.length}
                label="Active incidents"
                hint="detecting & diagnosing"
                onClick={() => setView("incidents")}
              />
              <StatCard
                icon={<IconPR size={17} />}
                tint="var(--amber)"
                bg="var(--amber-dim)"
                value={openPrs.length}
                label="Awaiting review"
                hint="remediation PRs open"
                onClick={() => setView("prs")}
              />
              <StatCard
                icon={<IconCheck size={17} />}
                tint="var(--green)"
                bg="var(--green-dim)"
                value={resolved.length}
                label="Verified fixes"
                hint="metric confirmed healthy"
                onClick={() => setView("verifications")}
              />
              <StatCard
                icon={<IconDollar size={17} />}
                tint="var(--brand)"
                bg="rgba(124,157,255,0.14)"
                value={money(savings)}
                label="Cost impact / mo"
                hint="across proposed fixes"
                onClick={() => setView("prs")}
              />
            </div>

            <div className="overview-grid">
              <PreviewPanel
                icon={<IconAlert size={15} />}
                tint="var(--red)"
                bg="var(--red-dim)"
                title="Latest Incident"
                count={active.length}
                onMore={() => setView("incidents")}
                empty="No active incidents"
                loading={loading}
              >
                {active[0] && <IncidentCard incident={active[0]} />}
              </PreviewPanel>

              <PreviewPanel
                icon={<IconPR size={15} />}
                tint="var(--amber)"
                bg="var(--amber-dim)"
                title="Latest Pull Request"
                count={openPrs.length}
                onMore={() => setView("prs")}
                empty="No remediation PRs open"
                loading={loading}
              >
                {openPrs[0] && (
                  <PullRequestCard
                    incident={openPrs[0]}
                    onVerify={handleVerify}
                    verifying={verifyingId === openPrs[0].id}
                  />
                )}
              </PreviewPanel>

              <PreviewPanel
                icon={<IconCheck size={15} />}
                tint="var(--green)"
                bg="var(--green-dim)"
                title="Latest Verified Fix"
                count={resolved.length}
                onMore={() => setView("verifications")}
                empty="No verified resolutions yet"
                loading={loading}
              >
                {resolved[0] && <ResolvedCard incident={resolved[0]} />}
              </PreviewPanel>
            </div>
          </>
        )}

        {/* ---------------- INCIDENTS (full history) ---------------- */}
        {view === "incidents" && (
          <div className="list">
            {loading && <div className="skeleton skeleton-card" />}
            {!loading && incidents.length === 0 && <div className="empty">No incidents recorded</div>}
            {incidents
              .filter((i) => i.status !== "RESOLVED_VERIFIED")
              .map((inc) =>
                inc.pull_request && (inc.status === "PR_OPEN" || inc.status === "DEPLOYING") ? (
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
            {!loading && incidents.filter((i) => i.status !== "RESOLVED_VERIFIED").length === 0 && (
              <div className="empty">No open incidents — all clear</div>
            )}
          </div>
        )}

        {/* ---------------- PULL REQUESTS (full history) ---------------- */}
        {view === "prs" && (
          <div className="list">
            {loading && <div className="skeleton skeleton-card" />}
            {!loading &&
              incidents.filter((i) => i.pull_request).length === 0 && (
                <div className="empty">No remediation pull requests yet</div>
              )}
            {incidents
              .filter((i) => i.pull_request)
              .map((inc) =>
                inc.status === "RESOLVED_VERIFIED" ? (
                  <ResolvedCard key={inc.id} incident={inc} />
                ) : (
                  <PullRequestCard
                    key={inc.id}
                    incident={inc}
                    onVerify={handleVerify}
                    verifying={verifyingId === inc.id}
                  />
                )
              )}
          </div>
        )}

        {/* ---------------- VERIFICATIONS (full history) ---------------- */}
        {view === "verifications" && (
          <div className="list">
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
          </div>
        )}

        {/* ---------------- READ-ONLY AUDIT (governance) ---------------- */}
        {view === "audit" && (
          <div className="list">
            {loading && <div className="skeleton skeleton-card" />}
            {!loading && withAudit.length === 0 && (
              <div className="empty">No audited agent activity yet</div>
            )}
            {withAudit.map((inc) => (
              <AuditRecord key={inc.id} incident={inc} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

/* ---------- small presentational helpers ---------- */

function StatCard(props: {
  icon: JSX.Element;
  tint: string;
  bg: string;
  value: number | string;
  label: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button className="stat" onClick={props.onClick}>
      <div className="stat__icon" style={{ background: props.bg, color: props.tint }}>
        {props.icon}
      </div>
      <div className="stat__value">{props.value}</div>
      <div className="stat__label">{props.label}</div>
      <div className="stat__hint">{props.hint}</div>
    </button>
  );
}

function PreviewPanel(props: {
  icon: JSX.Element;
  tint: string;
  bg: string;
  title: string;
  count: number;
  onMore: () => void;
  empty: string;
  loading: boolean;
  children?: React.ReactNode;
}) {
  const hasChild = !!props.children;
  return (
    <div className="panel">
      <div className="panel__head">
        <span className="panel__icon" style={{ background: props.bg, color: props.tint }}>
          {props.icon}
        </span>
        <span className="panel__title">{props.title}</span>
        <span className="panel__count">{props.count}</span>
      </div>
      {props.loading ? (
        <div className="skeleton skeleton-card" />
      ) : hasChild ? (
        <>
          {props.children}
          {props.count > 1 && (
            <button className="panel__more" onClick={props.onMore}>
              View all {props.count} →
            </button>
          )}
        </>
      ) : (
        <div className="empty">{props.empty}</div>
      )}
    </div>
  );
}

// Audit view reuses the correct card per incident type so the read-only trail shows in context.
function AuditRecord({ incident }: { incident: Incident }) {
  if (incident.status === "RESOLVED_VERIFIED") return <ResolvedCard incident={incident} />;
  if (incident.pull_request) {
    // Render as an incident-style card (no verify button noise in the audit view).
    return <IncidentCard incident={incident} />;
  }
  return <IncidentCard incident={incident} />;
}
