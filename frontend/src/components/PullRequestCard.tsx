import { useState } from "react";
import type { Incident } from "../types/incident";
import { money, relativeTime } from "../utils/format";
import { AuditPanel } from "./AuditPanel";
import { CdkDiff } from "./CdkDiff";
import { IconCheck, IconExternal } from "./icons";

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
  const deltaCls = delta > 0 ? "cost__v--pos" : "cost__v--neg";
  const deltaLabel = `${delta >= 0 ? "+" : ""}${money(delta)}`;

  return (
    <div className="card">
      <div className="card__top">
        <h3 className="card__title">{incident.title}</h3>
        <span className={`pill pill--${incident.severity}`}>{incident.severity}</span>
      </div>
      <div className="card__meta">
        <a href={pr.url} target="_blank" rel="noreferrer" className="tag">
          PR #{pr.number} <IconExternal size={11} />
        </a>
        <span className="dot" />
        <span>{incident.resource_id}</span>
        <span className="dot" />
        <span>{relativeTime(pr.opened_at)}</span>
      </div>

      {incident.diagnosis && (
        <div className="section">
          <div className="section__label">Diagnosis</div>
          <p className="section__text">{incident.diagnosis}</p>
        </div>
      )}

      <div className="section">
        <div className="section__label">
          <span>Proposed change · cdk diff</span>
          <button className="btn btn--ghost" onClick={() => setShowDiff((v) => !v)}>
            {showDiff ? "Hide" : "Show"}
          </button>
        </div>
        {showDiff && <CdkDiff diff={pr.cdk_diff} />}
      </div>

      <div className="section">
        <div className="section__label">Cost impact / month</div>
        <div className="cost">
          <div className="cost__item">
            <div className="cost__k">Before</div>
            <div className="cost__v">{money(pr.cost_delta.before_monthly_usd)}</div>
          </div>
          <div className="cost__item">
            <div className="cost__k">After</div>
            <div className="cost__v">{money(pr.cost_delta.after_monthly_usd)}</div>
          </div>
          <div className="cost__item">
            <div className="cost__k">Delta</div>
            <div className={`cost__v ${deltaCls}`}>{deltaLabel}</div>
          </div>
        </div>
      </div>

      <div className="section">
        <div className="section__label">Rollback plan</div>
        <p className="section__text">{pr.rollback_plan}</p>
      </div>

      <AuditPanel calls={incident.audit_calls} />

      <div className="section">
        <button
          className="btn btn--primary"
          onClick={() => onVerify(incident.id)}
          disabled={verifying}
          style={{ width: "100%", justifyContent: "center" }}
        >
          <IconCheck size={14} />
          {verifying ? "Verifying…" : "Simulate merge & verify fix"}
        </button>
      </div>
    </div>
  );
}
