import type { Incident } from "../types/incident";
import { formatTime, relativeTime } from "../utils/format";
import { AuditPanel } from "./AuditPanel";
import { IconExternal } from "./icons";

interface Props {
  incident: Incident;
}

/** Verified resolution card — the primary proof: metric confirmed healthy post-deploy. */
export function ResolvedCard({ incident }: Props) {
  const v = incident.verification;
  return (
    <div className="card">
      <div className="card__top">
        <h3 className="card__title">{incident.title}</h3>
        <span className={`pill pill--${incident.severity}`}>{incident.severity}</span>
      </div>
      <div className="card__meta">
        <span>{incident.resource_id}</span>
        <span className="dot" />
        <span>{incident.metric_name}</span>
        <span className="dot" />
        <span>{relativeTime(incident.updated_at)}</span>
      </div>

      {v && (
        <div className="section">
          <div className="verified">
            <span className="verified__check">✓</span>
            <span>
              {v.summary}
              <br />
              <strong>Verified {formatTime(v.verified_at)}.</strong>
            </span>
          </div>
        </div>
      )}

      {incident.pull_request && (
        <div className="section">
          <div className="section__label">Fix shipped via</div>
          <a href={incident.pull_request.url} target="_blank" rel="noreferrer" className="tag">
            PR #{incident.pull_request.number} <IconExternal size={11} />
          </a>
        </div>
      )}

      <AuditPanel calls={incident.audit_calls} />
    </div>
  );
}
