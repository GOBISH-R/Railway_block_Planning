import type { ThemePreference } from "../../state/useTheme";
import "./ThemeToggle.css";

const OPTIONS: Array<{ value: ThemePreference; label: string; hint: string }> = [
  { value: "system", label: "System", hint: "Follow this machine's setting" },
  { value: "light", label: "Light", hint: "Always light -- the presentation theme" },
  { value: "dark", label: "Dark", hint: "Always dark" },
];

/**
 * Three-segment theme control, in the header's existing right-hand slot.
 *
 * A segmented control rather than a sun/moon icon button: with three states an
 * icon cannot say which one is active, and "System" has no icon anyone reads
 * correctly. It is also the only honest way to show that the default is still
 * "follow the OS" rather than a theme someone picked.
 */
export function ThemeToggle({
  preference,
  onChange,
}: {
  preference: ThemePreference;
  onChange: (next: ThemePreference) => void;
}) {
  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {OPTIONS.map((o) => {
        const active = preference === o.value;
        return (
          <button
            key={o.value}
            type="button"
            className={`theme-toggle__option ${active ? "theme-toggle__option--active" : ""}`}
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            title={o.hint}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
