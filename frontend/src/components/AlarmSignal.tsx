import type { Incident } from "../types/incident";
import { IconActivity } from "./icons";

interface Props {
  incident: Incident;
}

/**
 * Shows the CloudWatch alarm payload this incident was derived from.
 *
 * This is deliberately visible: the resource, metric and dimension set are read
 * from the alarm at detection time, not hardcoded, and the verification step
 * later re-reads this exact metric. Showing the payload lets a reviewer confirm
 * that rather than take it on trust.
 */
export function AlarmSignal({ incident }: Props) {
  const dims = incident.metric_dimensions ?? {};
  const dimEntries = Object.entries(dims);
  // Nothing to show for records created before the alarm identity was captured.
  if (!incident.alarm_name && dimEntries.length === 0) return null;

  const metric = incident.metric_namespace
    ? `${incident.metric_namespace}/${incident.metric_name}`
    : incident.metric_name;

  return (
    <div className="signal">
      <div className="signal__head">
        <span className="signal__title">
          <IconActivity size={13} /> Detected from CloudWatch alarm
        </span>
        <span className="signal__verdict">READ FROM PAYLOAD</span>
      </div>

      <div className="signal__grid">
        {incident.alarm_name && (
          <Row label="Alarm" value={incident.alarm_name} />
        )}
        <Row label="Metric" value={metric} />
        {incident.metric_statistic && (
          <Row label="Statistic" value={incident.metric_statistic} />
        )}
        <Row label="Resource" value={`${incident.resource_id} (${incident.resource_type})`} />
      </div>

      {dimEntries.length > 0 && (
        <div className="signal__dims">
          <div className="signal__dimsLabel">Metric dimensions</div>
          <div className="signal__chips">
            {dimEntries.map(([k, v]) => (
              <span className="signal__chip" key={k}>
                <b>{k}</b>={v}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="signal__row">
      <span className="signal__k">{label}</span>
      <span className="signal__v">{value}</span>
    </div>
  );
}
