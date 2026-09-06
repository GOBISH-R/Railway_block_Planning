import type {
  ComparisonResponse,
  CorridorResponse,
  DemandResponse,
  JobExplanation,
  BlockExplanation,
  PlanRequest,
  PlanResponse,
  ScenariosResponse,
  TrafficResponse,
  ApiErrorBody,
} from "./types";

// In dev, Vite's proxy (vite.config.ts) forwards /api/* to the backend, so no
// CORS round-trip is needed and no base URL is hard-coded into the bundle.
const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as ApiErrorBody;
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body; fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  corridor: () => request<CorridorResponse>("/corridor"),

  scenarios: () => request<ScenariosResponse>("/scenarios"),

  demand: (scenario: string) =>
    request<DemandResponse>(`/demand?scenario=${encodeURIComponent(scenario)}`),

  traffic: (scenario: string, sectionId?: string) => {
    const params = new URLSearchParams({ scenario });
    if (sectionId) params.set("section_id", sectionId);
    return request<TrafficResponse>(`/traffic?${params.toString()}`);
  },

  createPlan: (body: PlanRequest) =>
    request<PlanResponse>("/plan", { method: "POST", body: JSON.stringify(body) }),

  getPlan: (planId: string) => request<PlanResponse>(`/plan/${encodeURIComponent(planId)}`),

  explainBlock: (planId: string, blockId: string) =>
    request<BlockExplanation>(
      `/plan/${encodeURIComponent(planId)}/block/${encodeURIComponent(blockId)}`
    ),

  explainJob: (planId: string, jobId: string) =>
    request<JobExplanation>(
      `/plan/${encodeURIComponent(planId)}/explain/${encodeURIComponent(jobId)}`,
      { method: "POST" }
    ),

  comparison: () => request<ComparisonResponse>("/comparison"),
};
