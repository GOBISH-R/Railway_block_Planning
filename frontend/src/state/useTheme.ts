import { useEffect, useState } from "react";

/**
 * Theme preference and the resolved theme it produces.
 *
 * "system" is the default and follows the OS, which is what the app did before
 * a control existed. The two explicit values exist because the OS is not always
 * the right answer: on a projector, light is the presentation theme whatever
 * the laptop happens to be set to, and a controller should not have to change
 * a machine-wide setting to get it.
 */
export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "blockplan-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function prefersDark(): boolean {
  try {
    return window.matchMedia(DARK_QUERY).matches;
  } catch {
    return false;
  }
}

/** The same rule the inline script in index.html applies before first paint. */
export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "system") return prefersDark() ? "dark" : "light";
  return preference;
}

export function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    // Blocked storage is not an error here -- it just means "no preference".
    return "system";
  }
}

/**
 * Owns the theme preference, persists it, and keeps <html data-theme> in step.
 *
 * The attribute is what tokens.css selects on, so this hook is the only place
 * that decides which palette is active. No component reads the theme; they all
 * read semantic variables that resolve differently underneath.
 */
export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(readStoredPreference);
  // Only the OS reading is state. The resolved theme is derived from it during
  // render rather than stored, so there is one source of truth and no effect
  // that has to write it back.
  const [systemDark, setSystemDark] = useState<boolean>(prefersDark);

  const resolved: ResolvedTheme =
    preference === "system" ? (systemDark ? "dark" : "light") : preference;

  // Sync the two things outside React: the attribute tokens.css selects on,
  // and the stored preference. "system" removes the key rather than storing
  // the word, so a machine that later changes its OS setting is followed.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
    try {
      if (preference === "system") localStorage.removeItem(THEME_STORAGE_KEY);
      else localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch {
      // Blocked storage: the preference still applies for this session, it
      // just will not be remembered. Not worth failing a render over.
    }
  }, [preference, resolved]);

  // Track the OS unconditionally, not just while the preference is "system".
  // Keeping the reading current means switching back to System applies the
  // machine's setting immediately, including a change made while pinned.
  useEffect(() => {
    let media: MediaQueryList;
    try {
      media = window.matchMedia(DARK_QUERY);
    } catch {
      return;
    }
    const onChange = () => setSystemDark(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  return { preference, resolved, setPreference };
}
