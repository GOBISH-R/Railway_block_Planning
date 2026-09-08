"""Scale a job's criticality by which asset it is on and how exposed the section is.

    BLOCKPLAN_ASSET_IMPACT=0   every factor is 1.0, nothing changes  (DEFAULT)
    BLOCKPLAN_ASSET_IMPACT=1   apply the declared weighting
    BLOCKPLAN_ASSET_IMPACT_CONFIG=<path>   sweep a different weight file

DEFAULT OFF, and off means arithmetically inert: `Disabled` returns the jobs it
was given without touching them, so plan 2db53586d84f is unchanged.

core.py IS NOT TOUCHED. `criticality` reaches the optimiser through exactly one
expression -- core.deferral_penalty at core.py:677:

    j.criticality * 100.0 / (1.0 + slack)

so multiplying the field scales the cost of deferring that job and nothing
else. No other line of core reads it. That is what makes this safe to do from
outside rather than by editing the penalty function.

THE WEIGHTS ARE CLASS E -- ASSUMED. Not measured, not from Indian Railways, not
fitted. They live in asset_impact.yaml so the judgement is visible and
sweepable, and anything computed with them inherits that provenance grade. The
Why panel is told, so a scaled figure cannot be read as source data.

COMPANIONS ARE UNAFFECTED, and not by choice here. core.py gives every
rule-generated companion `criticality=0.0` (core.py:249), so any factor
multiplies to zero. 63 of the 238 jobs are companions. A companion is scheduled
because a rule compels it, not because it is urgent, and this does not change
that.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from . import paths

ENV_VAR = "BLOCKPLAN_ASSET_IMPACT"
CONFIG_ENV_VAR = "BLOCKPLAN_ASSET_IMPACT_CONFIG"

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "asset_impact.yaml")

#: Provenance grade, matching the dataset's own scale. Carried into the
#: explanation so a weighted number is never presented as measured.
PROVENANCE = "E:assumed_asset_impact_weighting"


class AssetImpactError(RuntimeError):
    """The weighting cannot be applied as configured."""


@runtime_checkable
class CriticalityWeighting(Protocol):
    """Adjusts the deferral urgency of the jobs about to be planned."""

    @property
    def enabled(self) -> bool:
        """False for the default, which changes nothing."""

    def apply(self, jobs: Sequence[Any]) -> Sequence[Any]:
        """Scale criticality in place and return the jobs."""

    def describe(self) -> str:
        """One line for /health and the plan response."""


class Disabled:
    """The default. Returns the jobs untouched."""

    enabled = False

    def apply(self, jobs: Sequence[Any]) -> Sequence[Any]:
        return jobs

    def describe(self) -> str:
        return "declared criticality (no asset weighting)"

    def __repr__(self) -> str:
        return "Disabled()"


@dataclass(frozen=True)
class Weights:
    """The declared assumptions, loaded from YAML."""

    asset: Mapping[str, float]
    default_asset_weight: float
    support_reference: float
    support_weight: float
    headway_reference: float
    headway_weight: float
    single_line: float
    clamp_min: float
    clamp_max: float
    source: str

    @classmethod
    def load(cls, path: str | None = None) -> "Weights":
        import yaml

        path = path or DEFAULT_CONFIG
        if not os.path.isfile(path):
            raise AssetImpactError(f"no asset-impact weights at {path}")
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        try:
            return cls(
                asset={str(k): float(v) for k, v in (raw.get("asset") or {}).items()},
                default_asset_weight=float(raw.get("default_asset_weight", 1.0)),
                support_reference=float(raw["support_trains"]["reference"]),
                support_weight=float(raw["support_trains"]["weight"]),
                headway_reference=float(raw["headway_min"]["reference"]),
                headway_weight=float(raw["headway_min"]["weight"]),
                single_line=float(raw.get("single_line", 1.0)),
                clamp_min=float(raw["clamp"]["min"]),
                clamp_max=float(raw["clamp"]["max"]),
                source=path,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AssetImpactError(f"{path}: malformed weights ({exc})") from exc

    def enabled_in_file(self, path: str | None = None) -> bool:
        import yaml

        with open(path or self.source, encoding="utf-8") as f:
            return bool((yaml.safe_load(f) or {}).get("enabled", False))


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def asset_by_activity(tree: paths.DatasetTree | None = None) -> dict[str, str]:
    """activity -> asset class, from activities.csv.

    Companion activities are not all catalogued -- four of the six exist only
    as pairing-rule targets -- so a lookup can legitimately miss. It does not
    matter here, because companions carry zero criticality anyway, but the
    caller must not assume the mapping is total.
    """
    directory = (tree.processed_dir if tree is not None else paths.PROCESSED_DIR)
    return {row["activity_id"]: row["asset"]
            for row in _read_csv(os.path.join(directory, "activities.csv"))}


def section_exposure(tree: paths.DatasetTree | None = None
                     ) -> dict[str, dict[str, float]]:
    """section_id -> the exposure fields the weighting reads."""
    path = tree.sections_csv if tree is not None else paths.SECTIONS_CSV
    return {
        row["section_id"]: {
            "support_trains": float(row["support_trains"]),
            "headway_min": float(row["headway_min"]),
            "is_single": float(row["is_single"]),
        }
        for row in _read_csv(path)
    }


class AssetImpact:
    """The weighting, applied to core.Job objects before the pipeline runs."""

    enabled = True

    def __init__(self, weights: Weights | None = None,
                 tree: paths.DatasetTree | None = None) -> None:
        self.weights = weights or Weights.load()
        self._asset = asset_by_activity(tree)
        self._exposure = section_exposure(tree)

    def factor(self, activity: str, section_id: str) -> float:
        """The multiplier for one job, clamped.

        Every term is declared in asset_impact.yaml; none is measured. The
        clamp is what stops an assumed weighting from overwhelming the
        criticality it is meant to modulate.
        """
        w = self.weights
        asset = self._asset.get(activity)
        factor = w.asset.get(asset, w.default_asset_weight)

        exposure = self._exposure.get(section_id)
        if exposure is not None:
            if w.support_weight and w.support_reference:
                ratio = exposure["support_trains"] / w.support_reference
                factor *= 1.0 + w.support_weight * (ratio - 1.0)
            if w.headway_weight and exposure["headway_min"]:
                ratio = w.headway_reference / exposure["headway_min"]
                factor *= 1.0 + w.headway_weight * (ratio - 1.0)
            if exposure["is_single"]:
                factor *= w.single_line

        return min(max(factor, w.clamp_min), w.clamp_max)

    def apply(self, jobs: Sequence[Any]) -> Sequence[Any]:
        """Scale criticality, and record what was done to each job.

        The original value and the factor are attached to the job so the
        explanation layer can show an adjusted number AS adjusted. core.Job is
        a plain dataclass and core reads neither attribute; nothing downstream
        of the optimiser changes because they exist.
        """
        for job in jobs:
            if job.criticality is None:
                continue
            factor = self.factor(job.activity, job.section_id)
            job.declared_criticality = job.criticality
            job.asset_impact_factor = factor
            job.criticality = job.criticality * factor
        return jobs

    def describe(self) -> str:
        return (f"asset-weighted criticality [{PROVENANCE}] "
                f"from {os.path.basename(self.weights.source)}")

    def __repr__(self) -> str:
        return f"AssetImpact(source={self.weights.source!r})"


def resolve(env: Mapping[str, str] | None = None) -> CriticalityWeighting:
    """Pick a weighting. Disabled unless both the flag and the file say on.

    Two switches, deliberately. The environment decides whether this deployment
    wants the weighting at all; the file records whether the weights themselves
    are considered ready. Requiring both means a half-edited weight file cannot
    change a plan because somebody exported a variable.
    """
    env = os.environ if env is None else env
    raw = env.get(ENV_VAR, "0").strip().lower()

    if raw in ("", "0", "false", "no", "off"):
        return Disabled()
    if raw not in ("1", "true", "yes", "on"):
        raise AssetImpactError(f"{ENV_VAR}={raw!r} is not a yes/no value. Use 1 or 0.")

    weights = Weights.load(env.get(CONFIG_ENV_VAR) or None)
    if not weights.enabled_in_file():
        raise AssetImpactError(
            f"{ENV_VAR} is on but {weights.source} has `enabled: false`. "
            "Set it in the weight file too -- these weights are assumptions "
            "(class E) and turning them on is a deliberate act.")
    return AssetImpact(weights)
