/**
 * The one place a scenario's display name is produced.
 *
 * Scenario values on the wire are upper-snake enums (`NORMAL_TRAFFIC`) and
 * must stay that way -- they are the API's `scenario` parameter and the key
 * into the frozen benchmark artefacts. This turns one into the label a person
 * reads ("Normal Traffic") and nothing else; callers keep passing the raw
 * value as the option's `value`.
 *
 * It lives here rather than beside either dropdown because the Plan and
 * Corridor views both need it, and having a private copy in one of them is
 * exactly how they came to disagree.
 */
export function scenarioLabel(name: string): string {
  return (
    name
      .toLowerCase()
      .split("_")
      // A stray leading, trailing or doubled underscore would otherwise index
      // into an empty string and throw.
      .filter((word) => word.length > 0)
      .map((word) => word[0].toUpperCase() + word.slice(1))
      .join(" ") || name
  );
}
