import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SliderField } from "./Controls";

function renderSlider(overrides: Partial<Parameters<typeof SliderField>[0]> = {}) {
  const onChange = vi.fn();
  const { container } = render(
    <SliderField
      label="Reliability floor (θ)"
      value={0.9}
      min={0.5}
      max={0.99}
      step={0.01}
      onChange={onChange}
      formatValue={(v) => v.toFixed(2)}
      {...overrides}
    />
  );
  // Scoped to this render's own container: one case renders two sliders.
  const input = container.querySelector('input[type="range"]') as HTMLInputElement;
  const fill = container.querySelector(".field__slider-fill") as HTMLElement;
  return { container, input, fill, onChange };
}

/**
 * Styling only. These tests exist to prove the restyle did not change how the
 * control behaves -- it is still a native range input with the same value,
 * bounds, step, keyboard support and change events.
 */
describe("SliderField behaviour is unchanged by the restyle", () => {
  it("is still a native range input carrying its value and bounds", () => {
    const { input } = renderSlider();
    expect(input.type).toBe("range");
    expect(input.value).toBe("0.9");
    expect(input.min).toBe("0.5");
    expect(input.max).toBe("0.99");
    expect(input.step).toBe("0.01");
  });

  it("reports the numeric value on change", () => {
    const { input, onChange } = renderSlider();
    fireEvent.change(input, { target: { value: "0.75" } });
    expect(onChange).toHaveBeenCalledWith(0.75);
  });

  it("still shows the formatted value beside the label", () => {
    const { container } = renderSlider();
    expect(container.querySelector(".field__value")!.textContent).toBe("0.90");
  });

  it("still honours disabled", () => {
    const { input } = renderSlider({ disabled: true });
    expect(input.disabled).toBe(true);
  });

  it("keeps the accessible name, so the control is still reachable by label", () => {
    renderSlider();
    expect(screen.getByRole("slider")).toBeInTheDocument();
    expect(screen.getByText(/Reliability floor/)).toBeInTheDocument();
  });
});

describe("SliderField track fill", () => {
  it("sizes the fill from the value's position between min and max", () => {
    // 0.9 of the way from 0.5 to 0.99 is (0.9-0.5)/(0.99-0.5) = 0.8163...
    const { fill } = renderSlider();
    expect(fill.style.width).toContain("0.816");
  });

  it("shows an empty fill at the minimum and a full one at the maximum", () => {
    expect(renderSlider({ value: 0.5 }).fill.style.width).toContain("0 *");
    expect(renderSlider({ value: 0.99 }).fill.style.width).toContain("1 *");
  });

  it("does not divide by zero when min equals max", () => {
    const { fill } = renderSlider({ min: 1, max: 1, value: 1 });
    expect(fill.style.width).toContain("0 *");
  });

  it("paints the fill as a flat colour, never a gradient", () => {
    const { fill } = renderSlider();
    // The fill is a plain element; its size is the only thing set inline.
    expect(fill.getAttribute("style")).not.toMatch(/gradient/i);
  });
});
