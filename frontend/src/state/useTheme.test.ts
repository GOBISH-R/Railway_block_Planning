import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  THEME_STORAGE_KEY,
  readStoredPreference,
  resolveTheme,
  useTheme,
} from "./useTheme";

/** Drives prefers-color-scheme, and lets a test fire an OS-level change. */
function mockMatchMedia(dark: boolean) {
  const listeners = new Set<() => void>();
  const mql = {
    matches: dark,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  };
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue(mql));
  return {
    setSystemDark(next: boolean) {
      mql.matches = next;
      listeners.forEach((fn) => fn());
    },
    listenerCount: () => listeners.size,
  };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("resolveTheme", () => {
  it("follows the OS when the preference is system", () => {
    mockMatchMedia(true);
    expect(resolveTheme("system")).toBe("dark");
    mockMatchMedia(false);
    expect(resolveTheme("system")).toBe("light");
  });

  it("ignores the OS when a theme is pinned -- the point of the control", () => {
    mockMatchMedia(true);
    expect(resolveTheme("light")).toBe("light");
    mockMatchMedia(false);
    expect(resolveTheme("dark")).toBe("dark");
  });
});

describe("readStoredPreference", () => {
  it("defaults to system when nothing is stored", () => {
    expect(readStoredPreference()).toBe("system");
  });

  it("reads a stored preference back", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredPreference()).toBe("dark");
  });

  it("treats an unrecognised stored value as system rather than trusting it", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredPreference()).toBe("system");
  });
});

describe("useTheme", () => {
  it("defaults to system and applies the OS theme", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("system");
    expect(result.current.resolved).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("pins light even when the OS is dark", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("light"));
    expect(result.current.resolved).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("persists an explicit choice", () => {
    mockMatchMedia(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("dark"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("clears storage when returning to system, so the OS takes over again", () => {
    mockMatchMedia(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("dark"));
    act(() => result.current.setPreference("system"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(result.current.resolved).toBe("light");
  });

  it("restores a stored preference on a later visit", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    mockMatchMedia(true);
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("follows a live OS change while the preference is system", () => {
    const media = mockMatchMedia(false);
    const { result } = renderHook(() => useTheme());
    expect(result.current.resolved).toBe("light");
    act(() => media.setSystemDark(true));
    expect(result.current.resolved).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("ignores a live OS change once a theme is pinned", () => {
    const media = mockMatchMedia(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("light"));
    act(() => media.setSystemDark(true));
    expect(result.current.resolved).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  /**
   * The OS is tracked even while a theme is pinned, so returning to System
   * applies the machine's CURRENT setting rather than the one it had when the
   * user pinned. A presenter who forces Light for the demo and later switches
   * back should get whatever the laptop is set to now.
   */
  it("picks up an OS change that happened while a theme was pinned", () => {
    const media = mockMatchMedia(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("light"));

    act(() => media.setSystemDark(true));
    expect(result.current.resolved).toBe("light"); // still pinned

    act(() => result.current.setPreference("system"));
    expect(result.current.resolved).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("keeps exactly one OS listener and releases it on unmount", () => {
    const media = mockMatchMedia(false);
    const { unmount } = renderHook(() => useTheme());
    expect(media.listenerCount()).toBe(1);
    unmount();
    expect(media.listenerCount()).toBe(0);
  });
});
