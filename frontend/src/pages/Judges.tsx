import { useEffect, useState } from "react";
import { api } from "../api/client";
import { IconAlert, IconCheck, IconExternal, IconPR, IconShield } from "../components/icons";
import type { Incident } from "../types/incident";

const REPO = "https://github.com/sabari-07/Agentsentry";
const PR_DOCS = `${REPO}/pull/4`;
const PR_PROOF = `${REPO}/pull/5`;

interface Props {
  onExit: () => void;
}

/**
 * A three-minute guided tour for reviewers: what this is, the evidence chain,
 * and direct links to the artefacts that prove each claim.
 */
export function Judges({ onExit }: Props) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [mode, setMode] = useState<string>("");

  useEffect(() => {
    void (async () => {
      try {
        const [items, health] = await Promise.all([api.listIncidents(), api.health()]);
        setIncidents(items);
        setMode(health.mode);
      } catch {
        /* the page is still readable without live counts */
      }
    })();
  }, []);

  const verified = incidents.filter((i) => i.status === "RESOLVED_VERIFIED").length;
  const openPrs = incidents.filter(
    (i) => (i.status === "PR_OPEN" || i.status === "DEPLOYING") && i.pull_request
  ).length;
  const auditCalls = incidents.reduce((n, i) => n + (i.audit_calls?.length ?? 0), 0);

  return (
    <div className="judges">
      <header className="judges__head">
        <div>
          <div className="judges__eyebrow">AWS Zero to Shipped · 3-minute tour</div>
          <h1 className="judges__title">
            The fix is a pull request,
            <br />
            and the proof is the metric.
          </h1>
          <p className="judges__lede">
            AgentSentry AI detects a real AWS incident, inspects the account read-only, opens a
            genuine pull request containing the fix, and then re-reads the live CloudWatch metric to
            record whether the fix actually held — including when it did not.
          </p>
        </div>
        <button className="btn" onClick={onExit}>
          Open the dashboard →
        </button>
      </header>

      {/* Live numbers */}
      <section className="judges__stats">
        <Stat value={mode === "live" ? "LIVE" : mode.toUpperCase() || "—"} label="Running against real AWS" />
        <Stat value={String(verified)} label="Verified resolutions" />
        <Stat value={String(openPrs)} label="Pull requests awaiting review" />
        <Stat value={String(auditCalls)} label="Recorded read-only API calls" />
      </section>

      {/* The evidence chain */}
      <section className="judges__section">
        <h2 className="judges__h2">1. What actually happened, in order</h2>
        <p className="judges__p">
          Every step below is real. The only thing I staged is the initial write burst, which stands
          in for a traffic spike.
        </p>
        <ol className="steps">
          <Step n="1" title="A real failure">
            A write burst exceeded the monitored DynamoDB table's 1 WCU. <b>121 PutItem requests were
            refused</b> with <code>ProvisionedThroughputExceededException</code>.
          </Step>
          <Step n="2" title="Detected without me">
            A CloudWatch alarm fired → EventBridge → the incident Lambda. The incident appeared on the
            dashboard on its own.
          </Step>
          <Step n="3" title="Inspected read-only">
            The agent called <code>DescribeTable</code> and <code>GetMetricStatistics</code> only, and
            recorded every call. No mutating API was used.
          </Step>
          <Step n="4" title="Grounded in AWS documentation">
            It queried the <b>AWS MCP Server (Agent Toolkit)</b> at runtime and cited the AWS docs it
            relied on. See section 6 of{" "}
            <a href={PR_DOCS} target="_blank" rel="noreferrer">
              PR #4 <IconExternal size={11} />
            </a>
            .
          </Step>
          <Step n="5" title="Proposed a reviewable fix">
            It created a branch, committed an incident report, and opened a pull request with a
            diagnosis, <code>cdk diff</code>, cost delta, alternatives considered, and a rollback plan.
          </Step>
          <Step n="6" title="A human merged">
            The agent never merges and never applies a change.
          </Step>
          <Step n="7" title="Then it measured the outcome">
            The verification loop re-read the live metric and published the number it found.
          </Step>
        </ol>
      </section>

      {/* The proof */}
      <section className="judges__section">
        <h2 className="judges__h2">2. The part that matters: it can fail, and it did</h2>
        <p className="judges__p">
          A tool that only observes can never be wrong about an outcome. This one can be. Open{" "}
          <a href={PR_PROOF} target="_blank" rel="noreferrer">
            PR #5 <IconExternal size={11} />
          </a>{" "}
          and read the two verification comments in order:
        </p>
        <div className="proof">
          <div className="proof__row proof__row--fail">
            <span className="proof__badge">❌ FAILED</span>
            <span>
              <code>ThrottledRequests</code> = <b>116</b> (threshold 1) — the metric was still
              breaching, so the agent refused to certify the fix and said so on the PR.
            </span>
          </div>
          <div className="proof__row proof__row--pass">
            <span className="proof__badge">✅ VERIFIED</span>
            <span>
              <code>ThrottledRequests</code> = <b>0</b> — the metric had genuinely recovered.
            </span>
          </div>
        </div>
        <p className="judges__note">
          Those two comments exist because of a bug I found while trying to make the verification fail
          on purpose: it was querying an incomplete CloudWatch dimension set, matching no metric, and
          reporting "healthy" every time. A verification step that cannot fail is indistinguishable
          from no verification at all.
        </p>
      </section>

      {/* Check it yourself */}
      <section className="judges__section">
        <h2 className="judges__h2">3. Check it yourself</h2>
        <ul className="judges__list">
          <li>
            <b>The dashboard</b> — click <i>Open the dashboard</i> above. The sidebar switches between
            Incidents, Pull requests, Verifications and the Read-only audit trail.
          </li>
          <li>
            <b>The pull requests</b> —{" "}
            <a href={`${REPO}/pulls`} target="_blank" rel="noreferrer">
              every one was authored by the agent <IconExternal size={11} />
            </a>
            , up to 7,004 characters of structured incident report.
          </li>
          <li>
            <b>Reproduce a live incident</b> — <code>python scripts/trigger_incident.py</code> causes
            real throttling; a new incident and a new PR appear within a few minutes.
          </li>
          <li>
            <b>The tests</b> — <code>pytest</code> in <code>backend/</code> runs 46 tests, including
            regression tests for the verification bug above.
          </li>
        </ul>
      </section>

      <section className="judges__section">
        <h2 className="judges__h2">4. What it deliberately does not do</h2>
        <ul className="judges__list">
          <li>It never applies a change. It opens a pull request; merging is a human action.</li>
          <li>
            It never mutates AWS. Inspection is <code>Describe*</code> / <code>Get*</code> /{" "}
            <code>List*</code> only, and every call is recorded.
          </li>
          <li>
            A language model never decides the fix. Deterministic rules read the observed state, so the
            same input always yields the same reviewable recommendation.
          </li>
          <li>It does not claim success it has not measured.</li>
        </ul>
      </section>

      <footer className="judges__foot">
        <span>
          <IconShield size={13} /> Read-only by construction · human-in-the-loop by design · 100% AWS
          Free Tier
        </span>
        <a href={REPO} target="_blank" rel="noreferrer">
          Repository <IconExternal size={11} />
        </a>
      </footer>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="judges__stat">
      <div className="judges__statValue">{value}</div>
      <div className="judges__statLabel">{label}</div>
    </div>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  const icon = n === "2" ? <IconAlert size={13} /> : n === "5" ? <IconPR size={13} /> : n === "7" ? <IconCheck size={13} /> : null;
  return (
    <li className="step">
      <span className="step__n">{n}</span>
      <div>
        <div className="step__title">
          {title} {icon}
        </div>
        <div className="step__body">{children}</div>
      </div>
    </li>
  );
}
