// Typed API client for the AgentSentry AI backend.
import type { AuditCall, Incident } from "../types/incident";

// Normalize: strip any trailing slash so `${BASE_URL}/api/...` never doubles up.
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`API ${path} failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listIncidents: () => request<Incident[]>("/api/incidents"),
  listActive: () => request<Incident[]>("/api/incidents/active"),
  listOpenPrs: () => request<Incident[]>("/api/incidents/open-prs"),
  listResolved: () => request<Incident[]>("/api/incidents/resolved"),
  getIncident: (id: string) => request<Incident>(`/api/incidents/${id}`),
  getAudit: (id: string) => request<AuditCall[]>(`/api/audit/${id}`),
  verify: (id: string) => request<Incident>(`/api/verification/${id}`, { method: "POST" }),
  health: () => request<{ status: string; mode: string; region: string }>("/api/health"),
};
