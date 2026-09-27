import type { Incident } from "../types/incident";
import { relativeTime } from "../utils/format";
import { AuditPanel } from "./AuditPanel";

interface Props {
  incident: Incident;
}

/** Active incident card: detected / diagnosing, with the read-only audit trail. */
export function IncidentCard({ incident }: Props) {
  return (
    <div className="card">
      <div className="card__row">
        <h3 className="card__title">{incident.title}</h3>
        <span className={`pill pill--${incident.severity}`}>{incident.severity}</span>
      </div>
      <div className="card__meta">
        {incident.resource_id} · {incident.metric_name} · {relativeTime(incident.detected_at)}
      </div>

      {incident.diagnosis && (
        <div className="card__section">
          <div className="card__label">Diagnosis</div>
          <p className="card__text">{incident.diagnosis}</p>
        </div>
      )}
      {!incident.diagnosis && (
        <div className="card__section">
          <p className="card__text" style={{ color: "var(--text-dim)" }}>
            Agent inspecting live metrics (read-only)…
          </p>
        </div>
      )}

      <AuditPanel calls={incident.audit_calls} />
    </div>
  );
}
