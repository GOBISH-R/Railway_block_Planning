import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "./ThemeToggle";

function renderToggle(preference: "system" | "light" | "dark" = "system") {
  const onChange = vi.fn();
  const { container } = render(
    <ThemeToggle preference={preference} onChange={onChange} />
  );
  return { container, onChange };
}

describe("ThemeToggle", () => {
  it("offers all three states, System first", () => {
    const { container } = renderToggle();
    const labels = Array.from(
      container.querySelectorAll(".theme-toggle__option")
    ).map((b) => b.textContent);
    expect(labels).toEqual(["System", "Light", "Dark"]);
  });

  it("marks only the active preference as pressed", () => {
    const { container } = renderToggle("light");
    const pressed = Array.from(container.querySelectorAll("button")).filter(
      (b) => b.getAttribute("aria-pressed") === "true"
    );
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toBe("Light");
  });

  it("reports the chosen preference", () => {
    const { onChange } = renderToggle("system");
    fireEvent.click(screen.getByText("Light"));
    expect(onChange).toHaveBeenCalledWith("light");
  });

  it("can return to System, so the OS takes over again", () => {
    const { onChange } = renderToggle("dark");
    fireEvent.click(screen.getByText("System"));
    expect(onChange).toHaveBeenCalledWith("system");
  });

  it("is a labelled group, not three unrelated buttons", () => {
    const { container } = renderToggle();
    const group = container.querySelector('[role="group"]');
    expect(group).not.toBeNull();
    expect(group!.getAttribute("aria-label")).toBe("Colour theme");
  });

  it("names Light as the presentation theme in its tooltip", () => {
    renderToggle();
    expect(screen.getByText("Light").getAttribute("title")).toContain("presentation");
  });
});
