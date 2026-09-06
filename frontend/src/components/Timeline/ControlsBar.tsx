import type { ScenarioRow } from "../../api/types";
import { Button, NumberField, Select, SliderField } from "../shared/Controls";
import { scenarioLabel } from "../shared/scenarioLabel";
import "./ControlsBar.css";

export function ControlsBar({
  scenarios,
  scenario,
  onScenarioChange,
  theta,
  onThetaChange,
  horizonDays,
  onHorizonChange,
  onReplan,
  isPlanning,
}: {
  scenarios: ScenarioRow[];
  scenario: string;
  onScenarioChange: (s: string) => void;
  theta: number;
  onThetaChange: (t: number) => void;
  horizonDays: number;
  onHorizonChange: (h: number) => void;
  onReplan: () => void;
  isPlanning: boolean;
}) {
  const active = scenarios.find((s) => s.name === scenario);

  return (
    <div className="controls-bar">
      <Select
        label="Scenario"
        value={scenario}
        onChange={onScenarioChange}
        disabled={isPlanning}
        options={scenarios.map((s) => ({ value: s.name, label: scenarioLabel(s.name) }))}
      />

      <SliderField
        label="Reliability floor (θ)"
        value={theta}
        min={0.5}
        max={0.99}
        step={0.01}
        onChange={onThetaChange}
        formatValue={(v) => v.toFixed(2)}
        disabled={isPlanning}
      />

      <NumberField
        label="Horizon (days)"
        value={horizonDays}
        min={1}
        max={30}
        onChange={onHorizonChange}
        disabled={isPlanning}
      />

      <Button onClick={onReplan} disabled={isPlanning}>
        {isPlanning ? "Planning…" : "Re-plan"}
      </Button>

      {active && (
        <p className="controls-bar__note" title={active.note}>
          {active.note}
        </p>
      )}
    </div>
  );
}
