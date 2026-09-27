import type { AuditCall } from "../types/incident";
import { formatTime } from "../utils/format";
import { IconShield } from "./icons";

interface Props {
  calls: AuditCall[];
}

/**
 * CloudTrail read-only audit proof (secondary proof layer).
 * Shows the agent's management events were all read-only (Describe/Get/List).
 */
export function AuditPanel({ calls }: Props) {
  if (calls.length === 0) return null;
  const allReadOnly = calls.every((c) => c.read_only);

  return (
    <div className="audit">
      <div className="audit__head">
        <span className="audit__title">
          <IconShield size={13} /> Read-only audit · CloudTrail
        </span>
        {allReadOnly && <span className="audit__verdict">✓ ALL READ-ONLY</span>}
      </div>
      {calls.map((call, i) => (
        <div className="audit__row" key={`${call.event_name}-${i}`}>
          <span className="audit__name">{call.event_name}</span>
          <span className="audit__svc">
            {call.aws_service.replace(".amazonaws.com", "")} · {formatTime(call.event_time)}
          </span>
          {call.read_only && <span className="audit__ro">READ-ONLY</span>}
        </div>
      ))}
    </div>
  );
}
