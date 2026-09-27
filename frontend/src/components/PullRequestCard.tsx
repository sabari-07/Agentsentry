import { useState } from "react";
import type { Incident } from "../types/incident";
import { money, relativeTime } from "../utils/format";
import { AuditPanel } from "./AuditPanel";

interface Props {
  incident: Incident;
  onVerify: (id: string) => void;
  verifying: boolean;
}

/** Open remediation PR card: the "PR as hero" artifact (diff + cost delta + rollback). */
export function PullRequestCard({ incident, onVerify, verifying }: Props) {
  const pr = incident.pull_request;
  const [showDiff, setShowDiff] = useState(true);
  if (!pr) return null;

  const delta = pr.cost_delta.after_monthly_usd - pr.cost_delta.before_monthly_usd;
  const deltaLabel = `${delta >= 0 ? "+" : ""}${money(delta)}/mo`;

  return (
    <div className="card">
      <div className="card__row">
        <h3 className="card__title">{incident.title}</h3>
        <span className={`pill pill--${incident.severity}`}>{incident.severity}</span>
      </div>
      <div className="card__meta">
        <a href={pr.url} target="_blank" rel="noreferrer">
          PR #{pr.number}
        </a>{" "}
        · {incident.resource_id} · {relativeTime(pr.opened_at)}
      </div>

      {incident.diagnosis && (
        <div className="card__section">
          <div className="card__label">Diagnosis</div>
          <p className="card__text">{incident.diagnosis}</p>
        </div>
      )}

      <div className="card__section">
        <div className="card__row">
          <div className="card__label">Proposed change (cdk diff)</div>
          <button className="btn" onClick={() => setShowDiff((v) => !v)}>
            {showDiff ? "Hide" : "Show"}
          </button>
        </div>
        {showDiff && <pre className="code">{pr.cdk_diff}</pre>}
      </div>

      <div className="card__section">
        <div className="card__label">Cost delta</div>
        <div className="cost">
          <div className="cost__item">
            before<strong>{money(pr.cost_delta.before_monthly_usd)}</strong>
          </div>
          <div className="cost__item">
            after<strong>{money(pr.cost_delta.after_monthly_usd)}</strong>
          </div>
          <div className="cost__item">
            delta<strong>{deltaLabel}</strong>
          </div>
        </div>
      </div>

      <div className="card__section">
        <div className="card__label">Rollback plan</div>
        <p className="card__text">{pr.rollback_plan}</p>
      </div>

      <AuditPanel calls={incident.audit_calls} />

      <div className="card__section">
        <button className="btn" onClick={() => onVerify(incident.id)} disabled={verifying}>
          {verifying ? "Verifying…" : "Simulate merge + verify"}
        </button>
      </div>
    </div>
  );
}
