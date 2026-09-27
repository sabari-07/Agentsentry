// Shared types mirroring the backend pydantic models.

export type IncidentStatus =
  | "PENDING"
  | "DIAGNOSING"
  | "PR_OPEN"
  | "DEPLOYING"
  | "RESOLVED_VERIFIED"
  | "FAILED";

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface CostDelta {
  before_monthly_usd: number;
  after_monthly_usd: number;
  currency: string;
}

export interface PullRequest {
  number: number;
  url: string;
  title: string;
  branch: string;
  cdk_diff: string;
  rollback_plan: string;
  cost_delta: CostDelta;
  opened_at: string;
}

export interface AuditCall {
  event_name: string;
  event_time: string;
  aws_service: string;
  read_only: boolean;
  principal: string;
}

export interface VerificationResult {
  metric_name: string;
  healthy: boolean;
  observed_value: number;
  threshold: number;
  window_minutes: number;
  verified_at: string;
  summary: string;
}

export interface Incident {
  id: string;
  title: string;
  resource_id: string;
  resource_type: string;
  metric_name: string;
  severity: Severity;
  status: IncidentStatus;
  diagnosis: string | null;
  detected_at: string;
  updated_at: string;
  pull_request: PullRequest | null;
  verification: VerificationResult | null;
  audit_calls: AuditCall[];
}
