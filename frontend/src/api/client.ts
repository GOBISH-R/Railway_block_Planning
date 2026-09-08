import type {
  ComparisonResponse,
  CorridorResponse,
  HealthResponse,
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

/**
 * In-memory cache for the endpoints whose answer cannot change while the page
 * is open.
 *
 * The corridor, the scenario list, per-scenario demand and traffic, and the
 * benchmark comparison are all read straight off frozen artefacts on disk --
 * the backend cannot return a different answer to the same URL without being
 * restarted. Refetching them was costing a full round trip every time a tab
 * was revisited, which is the most-felt delay in the app: the planner solve is
 * slow because CP-SAT is slow, but switching from Block Plan to Corridor &
 * Demand and back was slow for no reason at all.
 *
 * Keyed by full path, so `/demand?scenario=HEAVY_FREIGHT` and
 * `/demand?scenario=NORMAL_TRAFFIC` are separate entries. The PROMISE is
 * stored rather than the resolved value, so two components mounting at once
 * share one request instead of racing. A rejected promise is evicted, so a
 * failed load is retried on the next attempt rather than caching the failure.
 *
 * `/health` is deliberately NOT cached -- it reports live service state and
 * has a refresh control behind it. Nor is `/plan`, which is a POST and whose
 * result depends on theta and the horizon.
 */
const immutableCache = new Map<string, Promise<unknown>>();

/**
 * Drop everything cached above.
 *
 * The cache has no expiry because nothing it holds can change while the
 * backend is up. If the backend is restarted against a different dataset with
 * the page left open, this is the escape hatch -- and it is what the client's
 * own tests use to stop one case's response leaking into the next.
 */
export function clearApiCache(): void {
  immutableCache.clear();
}

function cached<T>(path: string): Promise<T> {
  const hit = immutableCache.get(path);
  if (hit) return hit as Promise<T>;
  const pending = request<T>(path).catch((err) => {
    immutableCache.delete(path);
    throw err;
  });
  immutableCache.set(path, pending);
  return pending;
}

export const api = {
  corridor: () => cached<CorridorResponse>("/corridor"),

  scenarios: () => cached<ScenariosResponse>("/scenarios"),

  demand: (scenario: string) =>
    cached<DemandResponse>(`/demand?scenario=${encodeURIComponent(scenario)}`),

  traffic: (scenario: string, sectionId?: string) => {
    const params = new URLSearchParams({ scenario });
    if (sectionId) params.set("section_id", sectionId);
    return cached<TrafficResponse>(`/traffic?${params.toString()}`);
  },

  createPlan: (body: PlanRequest) =>
    request<PlanResponse>("/plan", { method: "POST", body: JSON.stringify(body) }),

  getPlan: (planId: string) => request<PlanResponse>(`/plan/${encodeURIComponent(planId)}`),

  // Safe to cache: `planId` identifies one immutable plan, so the explanation
  // for a block within it cannot change. Clicking back to a block already
  // looked at is then instant, which is how the Why panel is actually used.
  explainBlock: (planId: string, blockId: string) =>
    cached<BlockExplanation>(
      `/plan/${encodeURIComponent(planId)}/block/${encodeURIComponent(blockId)}`
    ),

  explainJob: (planId: string, jobId: string) =>
    request<JobExplanation>(
      `/plan/${encodeURIComponent(planId)}/explain/${encodeURIComponent(jobId)}`,
      { method: "POST" }
    ),

  comparison: () => cached<ComparisonResponse>("/comparison"),

  // Reports which data source, duration source and criticality weighting are
  // in force. Everything it returns is describe() prose or a plain count --
  // there is nothing here to parse, only to display.
  health: () => request<HealthResponse>("/health"),
};
