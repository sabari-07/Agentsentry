import type { Incident } from "../types/incident";
import { formatTime, relativeTime } from "../utils/format";
import { AuditPanel } from "./AuditPanel";

interface Props {
  incident: Incident;
}

/** Verified resolution card — the primary proof: metric confirmed healthy post-deploy. */
export function ResolvedCard({ incident }: Props) {
  const v = incident.verification;
  return (
    <div className="card">
      <div className="card__row">
        <h3 className="card__title">{incident.title}</h3>
        <span className={`pill pill--${incident.severity}`}>{incident.severity}</span>
      </div>
      <div className="card__meta">
        {incident.resource_id} · {incident.metric_name} · {relativeTime(incident.updated_at)}
      </div>

      {v && (
        <div className="card__section">
          <div className="verified">
            <span>✓</span>
            <span>
              {v.summary} Verified at {formatTime(v.verified_at)}.
            </span>
          </div>
        </div>
      )}

      {incident.pull_request && (
        <div className="card__section">
          <div className="card__meta">
            Fix shipped via{" "}
            <a href={incident.pull_request.url} target="_blank" rel="noreferrer">
              PR #{incident.pull_request.number}
            </a>
          </div>
        </div>
      )}

      <AuditPanel calls={incident.audit_calls} />
    </div>
  );
}
