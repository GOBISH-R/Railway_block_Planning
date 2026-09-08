import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, clearApiCache } from "./client";

function mockFetchOnce(status: number, body: unknown, statusText = "") {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText,
      json: async () => body,
    })
  );
}

describe("api client", () => {
  // The read-only endpoints are memoised for the lifetime of the page, so
  // without this a 200 recorded by one case is served to the next one that
  // asks for the same path -- which is how this suite first caught the cache
  // being introduced.
  beforeEach(clearApiCache);

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the parsed JSON body on a 200", async () => {
    mockFetchOnce(200, { scenarios: [] });
    const result = await api.scenarios();
    expect(result).toEqual({ scenarios: [] });
  });

  it("throws ApiError carrying the backend's own detail message on a 404", async () => {
    mockFetchOnce(404, { detail: "unknown scenario: NOPE" });
    await expect(api.demand("NOPE")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "unknown scenario: NOPE",
    });
  });

  it("falls back to statusText when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new SyntaxError("not json");
        },
      })
    );
    await expect(api.scenarios()).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });

  it("is a real ApiError instance, not a plain object, so callers can instanceof-check it", async () => {
    mockFetchOnce(422, { detail: "bad request" });
    try {
      await api.corridor();
      expect.unreachable("expected api.corridor() to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
    }
  });

  it("encodes the plan id and block id into the URL path for explainBlock", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchSpy);
    await api.explainBlock("plan/with slash", "B 01");
    const calledUrl = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain(encodeURIComponent("plan/with slash"));
    expect(calledUrl).toContain(encodeURIComponent("B 01"));
  });

  it("sends explainJob as a POST, matching the contract's verb", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchSpy);
    await api.explainJob("p1", "J1");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });
});

/**
 * The cache exists to stop tab-switching refetching frozen data. These pin
 * the two properties that make it safe to have at all.
 */
describe("api client caching", () => {
  beforeEach(clearApiCache);
  afterEach(() => vi.unstubAllGlobals());

  it("hits the network once for repeated reads of the same frozen resource", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ stations: [], sections: [] }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    // Concurrent, then sequential: both paths must collapse onto one request.
    await Promise.all([api.corridor(), api.corridor()]);
    await api.corridor();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("keys per scenario, so one scenario's demand is never served for another", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchSpy);

    await api.demand("NORMAL_TRAFFIC");
    await api.demand("HEAVY_FREIGHT");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("does not cache a failure, so a retry can still succeed", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, statusText: "Service Unavailable", json: async () => ({}) })
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ scenarios: [] }) });
    vi.stubGlobal("fetch", fetchSpy);

    await expect(api.scenarios()).rejects.toBeInstanceOf(ApiError);
    await expect(api.scenarios()).resolves.toEqual({ scenarios: [] });
  });
});
