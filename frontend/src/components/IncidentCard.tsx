import type { Incident } from "../types/incident";
import { relativeTime } from "../utils/format";
import { AlarmSignal } from "./AlarmSignal";
import { AuditPanel } from "./AuditPanel";

interface Props {
  incident: Incident;
}

/** Active incident card: detected / diagnosing, with the read-only audit trail. */
export function IncidentCard({ incident }: Props) {
  const diagnosing = incident.status === "DIAGNOSING";
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
        <span>{relativeTime(incident.detected_at)}</span>
      </div>

      <div className="section">
        <div className="section__label">{diagnosing ? "Agent status" : "Detected"}</div>
        {incident.diagnosis ? (
          <p className="section__text">{incident.diagnosis}</p>
        ) : (
          <p className="section__text" style={{ color: "var(--brand)" }}>
            ● Agent inspecting live metrics via read-only MCP…
          </p>
        )}
      </div>

      <AlarmSignal incident={incident} />
      <AuditPanel calls={incident.audit_calls} />
    </div>
  );
}
