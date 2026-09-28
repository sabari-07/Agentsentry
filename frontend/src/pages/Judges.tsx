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
        <h2 className="judges__h2">1. One incident, seven steps, nothing staged</h2>
        <p className="judges__p">
          This is a single real incident from this AWS account, start to finish. The only thing I
          staged is the opening write burst, which stands in for a traffic spike. Everything after it
          happened on its own.
        </p>
        <ol className="steps">
          <Step
            n="1"
            title="Something actually broke"
            usually="Most demos describe a hypothetical outage."
            proof="CloudWatch ThrottledRequests"
          >
            A burst of writes hit a DynamoDB table provisioned at <b>1 WCU</b> — roughly one write per
            second. <b>121 <code>PutItem</code> requests were refused</b> with{" "}
            <code>ProvisionedThroughputExceededException</code>. Those are real rejected writes, not a
            simulated error code.
          </Step>

          <Step
            n="2"
            title="It noticed before I did"
            usually="A human spots the alarm and starts digging."
            proof="Lambda log, 20.7s execution"
          >
            A CloudWatch alarm fired, EventBridge routed it, and the incident Lambda woke up. An
            incident appeared on the dashboard <b>without anyone touching it</b>. I did not create the
            record, call an API, or paste anything in.
          </Step>

          <Step
            n="3"
            title="It looked, but never touched"
            usually="Agents get broad write access and you hope for the best."
            proof="Read-only audit trail in the UI"
          >
            To understand the failure it called <code>DescribeTable</code> (to read the billing mode and
            capacity) and <code>GetMetricStatistics</code> (to count the throttles). Both are read-only,
            and <b>every call is recorded and shown per incident</b>. No mutating API was used at any
            point — that is a property of the design, not a promise.
          </Step>

          <Step
            n="4"
            title="It checked the AWS documentation, live"
            usually="The fix comes from a language model's memory."
            proof={`Section 6 of PR #4`}
          >
            Before recommending anything it queried the <b>AWS MCP Server (Agent Toolkit for AWS)</b>{" "}
            over SigV4-signed HTTPS and searched current AWS documentation, then{" "}
            <b>cited the sources in the pull request</b>. So the recommendation is anchored to what AWS
            publishes today, not to my assumptions.{" "}
            <a href={PR_DOCS} target="_blank" rel="noreferrer">
              See the citations <IconExternal size={11} />
            </a>
          </Step>

          <Step
            n="5"
            title="The output is a pull request, not advice"
            usually="You get a dashboard, a summary, or a runbook to action yourself."
            proof="Up to 7,004 characters per PR"
          >
            It created a branch, committed an incident report, and <b>opened a real GitHub pull
            request</b> containing the diagnosis, a <code>cdk diff</code>, a cost delta
            (<b>$0.57/mo → $0.00/mo</b>), the alternatives it considered <i>and why it rejected them</i>,
            a rollback plan, and its own read-only audit trail. It is reviewable the way a colleague's
            PR is reviewable.
          </Step>

          <Step
            n="6"
            title="A human decides"
            usually="Auto-remediation applies changes and tells you afterwards."
            proof="Merging is a GitHub action"
          >
            The agent <b>never merges and never applies a change</b>. It has no path to mutate
            infrastructure. Nothing reaches the account unless a person clicks merge, which means the
            blast radius of a bad suggestion is a rejected pull request.
          </Step>

          <Step
            n="7"
            title="Then it proved whether the fix worked"
            usually="The incident is closed on the assumption that it did."
            proof="The two comments on PR #5"
          >
            After the merge it re-read the <b>live CloudWatch metric</b> and published the number it
            found. It records <code>RESOLVED_VERIFIED</code> only when the metric has genuinely
            recovered — and <code>FAILED</code> when it hasn't. That last step is the whole point, and
            section 2 below is the receipt.
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

function Step({
  n,
  title,
  usually,
  proof,
  children,
}: {
  n: string;
  title: string;
  usually: string;
  proof: string;
  children: React.ReactNode;
}) {
  const icon =
    n === "2" ? <IconAlert size={13} /> :
    n === "5" ? <IconPR size={13} /> :
    n === "7" ? <IconCheck size={13} /> :
    n === "3" ? <IconShield size={13} /> : null;

  return (
    <li className="step">
      <span className="step__n">{n}</span>
      <div className="step__main">
        <div className="step__title">
          {title} {icon}
        </div>
        <div className="step__body">{children}</div>
        <div className="step__foot">
          <span className="step__usually">
            <span className="step__usuallyKey">Usually:</span> {usually}
          </span>
          <span className="step__proof">{proof}</span>
        </div>
      </div>
    </li>
  );
}
