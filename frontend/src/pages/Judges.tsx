import { useEffect, useState } from "react";
import { api } from "../api/client";
import { IconAlert, IconCheck, IconExternal, IconPR, IconShield } from "../components/icons";
import type { Incident } from "../types/incident";

const REPO = "https://github.com/sabari-07/Agentsentry";
const PR_DOCS = `${REPO}/pull/4`;
const PR_PROOF = `${REPO}/pull/5`;
/** The run that withheld certification: ThrottledRequests = 116. */
const PROOF_WITHHELD = `${PR_PROOF}#issuecomment-5864794338`;
/** The run that confirmed recovery: ThrottledRequests = 0. */
const PROOF_CONFIRMED = `${PR_PROOF}#issuecomment-5864880540`;

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
        <h2 className="judges__h2">1. One incident, start to finish, nothing staged</h2>
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
            record, call an API, or paste anything in. The rule is not pinned to one alarm —{" "}
            <b>any CloudWatch alarm in the account</b> enters this pipeline.
          </Step>

          <Step
            n="2b"
            title="It worked out what broke, from the alarm itself"
            usually="The monitored resource is hardcoded, so it only ever handles one thing."
            proof="The 'Detected from CloudWatch alarm' panel on every card"
          >
            The handler reads the <b>resource, namespace, metric, statistic and the metric's full
            dimension set</b> straight out of the alarm payload. Nothing about the resource is
            hardcoded, so the same code path handles DynamoDB, Lambda, API Gateway, RDS, SQS and ECS.
            You can see the exact payload it read on each card in the dashboard.
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
            It creates one atomic commit containing the <b>actual CDK source edit</b> — switching
            <code>infra/agentsentry/stack.py</code> from fixed provisioned capacity to
            <code>PAY_PER_REQUEST</code> — together with the incident report. The real GitHub pull
            request also contains the diagnosis, a <code>cdk diff</code>, cost delta, alternatives,
            rollback plan, and read-only audit trail. If the expected source block is missing or
            changed, it refuses to open a report-only PR.
          </Step>

          <Step
            n="6"
            title="A human decides"
            usually="Auto-remediation applies changes and tells you afterwards."
            proof="Merging is a GitHub action"
          >
            The agent <b>never merges and never applies a change</b>. It has no path to mutate
            infrastructure. A person must approve the PR, and the merged IaC must then be deployed by
            the deployment pipeline. The blast radius of a bad suggestion is therefore a rejected
            pull request, not an unreviewed AWS mutation.
          </Step>

          <Step
            n="7"
            title="Then it proved whether the fix worked"
            usually="The incident is closed on the assumption that it did."
            proof="Verification comments on PR #5"
          >
            After deployment it re-read the <b>live CloudWatch metric</b> and published the number it
            found. It records <code>RESOLVED_VERIFIED</code> only when the metric has genuinely
            recovered, and withholds certification when it hasn't. That last step is the whole point,
            and section 2 below is the receipt.
          </Step>
        </ol>
      </section>

      {/* The proof */}
      <section className="judges__section">
        <h2 className="judges__h2">
          2. The check is real: it refuses to certify a fix it cannot measure
        </h2>
        <p className="judges__p">
          A tool that only reports can never be wrong about an outcome. This one is accountable for
          the outcome, so it has to be able to return a negative result. Here are two runs against
          the same incident, each a link to the comment the agent published on the pull request:
        </p>
        <div className="proof">
          <div className="proof__row proof__row--fail">
            <span className="proof__badge">❌ WITHHELD</span>
            <span>
              <code>ThrottledRequests</code> = <b>116</b> (threshold 1) — still breaching, so the
              agent <b>declined to certify the fix</b> and published that number.{" "}
              <a href={PROOF_WITHHELD} target="_blank" rel="noreferrer">
                Read the comment <IconExternal size={11} />
              </a>
            </span>
          </div>
          <div className="proof__row proof__row--pass">
            <span className="proof__badge">✅ CONFIRMED</span>
            <span>
              <code>ThrottledRequests</code> = <b>0</b> — the metric had genuinely recovered, so the
              incident became <code>RESOLVED_VERIFIED</code>.{" "}
              <a href={PROOF_CONFIRMED} target="_blank" rel="noreferrer">
                Read the comment <IconExternal size={11} />
              </a>
            </span>
          </div>
        </div>
        <p className="judges__note">
          Why this section exists: an earlier build of the verification queried an{" "}
          <b>incomplete CloudWatch dimension set</b>, matched no metric, and therefore reported
          "healthy" every single time. It could not fail, which made its successes meaningless. The
          fix was to send the complete dimension set and aggregate with <code>Sum</code> rather than{" "}
          <code>Maximum</code>, and there is now a regression test pinning both. If you scroll{" "}
          <a href={PR_PROOF} target="_blank" rel="noreferrer">
            the full comment history on PR #5 <IconExternal size={11} />
          </a>
          , the three earlier ✅ comments are that old build's false positives. They are left in place
          deliberately: they are the reason the two comments above can be trusted.
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
        <h2 className="judges__h2">4. Scope, stated plainly</h2>
        <ul className="judges__list">
          <li>
            <b>Detection is account-wide.</b> Any CloudWatch alarm entering <code>ALARM</code> routes
            into the pipeline; nothing is pinned to a single alarm or resource.
          </li>
          <li>
            <b>Resource identification covers 7 services</b> — DynamoDB, Lambda, API Gateway (v1 and
            v2), RDS, SQS and ECS. An unrecognised namespace is still recorded as an incident for
            visibility, it just receives no automated diagnosis.
          </li>
          <li>
            <b>Remediation rules currently cover DynamoDB throttling.</b> That is the one failure mode
            with a proven end-to-end fix; the others are detection-only today.
          </li>
          <li>
            <b>It only sees what you alarm on.</b> There is no auto-discovery of unmonitored
            resources, and I am not claiming any.
          </li>
          <li>
            <b>Pull requests can route per resource.</b> A resource-to-repository map chooses the PR
            destination. The current concrete transformer expects the supported AgentSentry CDK
            layout; another repository must provide that layout and its own deployment integration.
          </li>
        </ul>
      </section>

      <section className="judges__section">
        <h2 className="judges__h2">5. What it deliberately does not do</h2>
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
