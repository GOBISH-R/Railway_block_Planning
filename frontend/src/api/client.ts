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

// In dev, Vite's proxy (vite.config.ts) forwards /api/* to the backend on a
// different port, so calls are prefixed to reach it. In a production build,
// FastAPI serves both the API and these static files from the same origin
// (Phase 8 packaging), so the prefix must disappear -- the real routes are
// at /corridor, /plan, etc., not /api/corridor. Getting this wrong doesn't
// fail loudly: it 404s silently in production while working fine in `npm run
// dev`, so it is not a detail to get away with hard-coding.
const BASE = import.meta.env.DEV ? "/api" : "";

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
