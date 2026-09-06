"""
BlockPlan — reference implementation of the PS 26027 planning core.

This is the *algorithm skeleton* referred to in the technical blueprint.
It is deliberately one file so the whole mechanism can be read end to end;
the production layout splits it into the modules named in each section header.

Nothing here uses real Indian Railways data. Every numeric parameter is either
    RULE   - traced to a published Indian Railways manual (cited in the blueprint)
    DECL   - a declared modelling parameter we chose, editable, not a fact
    SYNTH  - synthetic instance data generated for demonstration
and is tagged as such at its definition.

Python 3.10+, needs: numpy, ortools
"""
from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from ortools.sat.python import cp_model

RNG = np.random.default_rng(20260905)

# ============================================================================
# 1. DATA MODEL  (production: blockplan/model.py)
# ============================================================================

DEPTS = ("ENGG", "SNT", "TRD")

# RULE: corridor block envelope. Railway Board / IRTMM Ch.5 norms.
#       single line: one 240-min block or two 150-min blocks; 120 exceptional.
ALLOWED_BLOCK_LENGTHS = (150, 240)
EXCEPTIONAL_LENGTH = 120

# DECL: reliability threshold. Policy parameter, exposed in the UI.
THETA = 0.90

# DECL: coordination penalty for multi-department blocks.
#       Each extra department inflates every job's duration spread by KAPPA and
#       adds LAMBDA_CLOSE minutes to every closing chain. These two numbers are
#       the entire quantitative content of "more departments = more risk".
#       They are ASSUMPTIONS, not measurements. Calibrating them is the single
#       highest-value thing real block-outcome data would buy us.
KAPPA = 0.15
LAMBDA_CLOSE = 6.0

# DECL: departmental closing-chain times (minutes), mean and sd.
#       Structure is RULE (three independent chains, block ends at the max);
#       these particular numbers are DECL.
CLOSING = {
    "ENGG": (12.0, 4.0),   # clear site, withdraw protection, hand back to SMs
    "SNT": (20.0, 7.0),    # reconnect, correspondence test, SM signs memo
    "TRD": (15.0, 5.0),    # withdraw staff, remove+verify earths, return ETR-3
}

# DECL: train priority weights. Calibration parameters, not railway policy.
TRAIN_WEIGHT = {
    "VANDE_BHARAT": 3.0,
    "RAJDHANI": 3.0,
    "EXPRESS": 2.0,
    "MEMU": 1.2,
    "PASSENGER": 1.2,
    "FREIGHT": 1.0,
}


@dataclass(frozen=True)
class Section:
    """A stretch of line that blocks are taken on."""
    id: str
    line: str                 # "SINGLE", "UP", "DN"
    is_single: bool
    headway_min: int          # RULE-ish: normal service headway, from the WTT
    degraded_factor: float    # DECL: headway multiplier under single-line working


@dataclass(frozen=True)
class Train:
    id: str
    section_id: str
    sched_min: int            # minutes from midnight, scheduled entry to section
    klass: str
    day_mask: int             # bitmask of days-of-week it runs; 127 = daily


@dataclass
class Job:
    """One maintenance activity awaiting a block."""
    id: str
    dept: str
    activity: str
    section_id: str           # section-line it must be worked on
    km_from: float
    km_to: float
    # --- required access rights (RULE: the three protection regimes) ---
    needs_T: bool             # traffic block
    needs_P: bool             # power block (OHE dead + earthed + ETR-3 permit)
    needs_D: bool             # S&T disconnection
    # --- Class D negations: work that needs the opposite of a block ---
    needs_train_movements: bool = False   # e.g. track-circuit shunting check
    needs_live_ohe: bool = False          # e.g. OHE measurement under load
    # --- duration model ---
    # These four fields carry no usable default. A dataset row that omits one is
    # malformed, and a silent fallback (the old 60 +- 12 min, due day 30,
    # criticality 1.0) turns that malformed row into a plausible-looking job that
    # then enters bundles, reliability draws and the objective without anyone
    # noticing. Declared as None and rejected in __post_init__ so the failure is
    # loud and points at the offending id. Python's dataclass ordering rules
    # forbid a non-default field after a defaulted one, hence the sentinel.
    dur_mean: float | None = None
    dur_sd: float | None = None
    # --- resources, deadlines, structure ---
    resources: tuple[str, ...] = ()
    due_day: int | None = None
    criticality: float | None = None  # DECL: relative cost of deferring, per day late
    parent_id: str | None = None          # set on auto-generated companions
    companions: tuple[str, ...] = ()      # RULE: mandatory pairings
    after: tuple[str, ...] = ()           # must run after these, same block

    REQUIRED = ("dur_mean", "dur_sd", "due_day", "criticality")

    def __post_init__(self) -> None:
        missing = [f for f in self.REQUIRED if getattr(self, f) is None]
        if missing:
            raise ValueError(
                f"job {self.id!r}: missing required planning field(s) "
                f"{', '.join(missing)}. These have no defensible default; fix "
                f"the source row rather than supplying one.")
        if self.dur_mean <= 0 or self.dur_sd <= 0:
            raise ValueError(
                f"job {self.id!r}: dur_mean and dur_sd must both be positive "
                f"(got {self.dur_mean}, {self.dur_sd}); the lognormal duration "
                f"model is undefined otherwise.")

    @property
    def is_companion(self) -> bool:
        return self.parent_id is not None


@dataclass(frozen=True)
class Window:
    """A candidate block opportunity: where, when, how long."""
    id: str
    section_id: str
    day: int
    start_min: int
    length: int
    traffic_cost: float       # weighted train-minutes, from the queue simulator

    @property
    def end_min(self) -> int:
        return self.start_min + self.length


@dataclass(frozen=True)
class Column:
    """A candidate decision: this bundle of jobs, in this window."""
    id: str
    job_ids: tuple[str, ...]
    window: Window
    reliability: float
    exp_overrun_cost: float
    total_cost: float


# ============================================================================
# 2. MANDATORY PAIRINGS  (production: blockplan/rules.py)
# ============================================================================
# RULE: each row traces to a manual and carries a confidence.
#
# There is exactly ONE source of truth for these rules and it is a CSV, not this
# file. A table hard-coded here as well would be a second copy that drifts: the
# previous copy already disagreed with the shipped rules on a companion activity
# name and on a confidence value, and neither the optimiser nor the tests could
# have told you which one was live. The table below starts EMPTY and is filled by
# load_pairing_rules(); a caller that forgets to load produces no companions,
# which expand_mandatory_pairings refuses to let pass silently.
#
# activity -> list of (compelled_dept, companion_activity, mean, sd, must_follow)

MANDATORY_PAIRING: dict[str, list[tuple[str, str, float, float, bool]]] = {}
_PAIRING_SOURCE: str | None = None


def load_pairing_rules(path: str) -> dict:
    """Load the authoritative mandatory-pairing rules from CSV.

    Accepts either column spelling in use across the project
    (`dur_mean_min`/`duration_mean_min`) so the standalone and dataset-backed
    copies of the file are both readable, and records where the rules came from
    so any report can name its own source.
    """
    import csv as _csv

    table: dict[str, list[tuple[str, str, float, float, bool]]] = {}
    with open(path, encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            mean = r.get("duration_mean_min", r.get("dur_mean_min"))
            sd = r.get("duration_sd_min", r.get("dur_sd_min"))
            if mean is None or sd is None:
                raise ValueError(f"{path}: row for {r.get('activity')!r} has no "
                                 f"duration mean/sd column")
            table.setdefault(r["activity"], []).append((
                r["compelled_dept"], r["companion_activity"],
                float(mean), float(sd),
                bool(int(r["must_follow_parent"])),
            ))
    if not table:
        raise ValueError(f"{path}: no mandatory-pairing rules found")

    global MANDATORY_PAIRING, _PAIRING_SOURCE
    MANDATORY_PAIRING = table
    _PAIRING_SOURCE = path
    return table


def expand_mandatory_pairings(jobs: list[Job]) -> list[Job]:
    """Turn every rule-mandated association into a real companion job.

    Doing this here rather than in the optimiser is the whole trick: after
    expansion, a mandatory pairing is just 'these jobs are in the same bundle',
    which the enumerator enforces structurally and the solver never sees.
    """
    if not MANDATORY_PAIRING:
        raise RuntimeError(
            "no mandatory-pairing rules are loaded. Call "
            "core.load_pairing_rules(<pairing_rules.csv>) first. Expanding with "
            "an empty rule table would silently produce single-department "
            "bundles and make the cross-department result meaningless.")
    out = list(jobs)
    for j in jobs:
        rules = MANDATORY_PAIRING.get(j.activity, [])
        comp_ids = []
        for k, (dept, act, mean, sd, must_follow) in enumerate(rules):
            cid = f"{j.id}c{k}"
            comp_ids.append(cid)
            out.append(Job(
                id=cid, dept=dept, activity=act,
                section_id=j.section_id, km_from=j.km_from, km_to=j.km_to,
                needs_T=True,
                needs_P=(dept == "TRD" and act != "TRACTION_BOND_JUMPER"),
                needs_D=(dept == "SNT"),
                dur_mean=mean, dur_sd=sd,
                due_day=j.due_day, criticality=0.0,
                parent_id=j.id,
                after=(j.id,) if must_follow else (),
            ))
        if comp_ids:
            j.companions = tuple(comp_ids)
    return out


# ============================================================================
# 3. COMPATIBILITY ENGINE  (production: blockplan/compat.py)
# ============================================================================

def footprints_overlap(a: Job, b: Job) -> bool:
    return a.km_from < b.km_to and b.km_from < a.km_to


def related(a: Job, b: Job) -> bool:
    """Parent/companion pair — allowed to occupy the same footprint."""
    return a.parent_id == b.id or b.parent_id == a.id or (
        a.parent_id is not None and a.parent_id == b.parent_id)


def pairwise_compatible(a: Job, b: Job) -> tuple[bool, str]:
    """Can these two jobs sit in one block? Returns (verdict, reason-if-not)."""
    if a.section_id != b.section_id:
        return False, "different section-line"

    # Class D — a job needing the negation of the block can never be bundled.
    if a.needs_train_movements or b.needs_train_movements:
        return False, "requires train movements; cannot sit inside a traffic block"
    if (a.needs_live_ohe and b.needs_P) or (b.needs_live_ohe and a.needs_P):
        return False, "contradictory OHE state: one needs it live, one needs it dead"

    # Spatial exclusion — same stretch at the same time, unless rule-paired.
    if footprints_overlap(a, b) and not related(a, b):
        return False, f"footprints overlap at km {max(a.km_from, b.km_from):.1f}"

    # Exclusive resources.
    clash = set(a.resources) & set(b.resources)
    if clash:
        return False, f"both need exclusive resource {sorted(clash)[0]}"

    # Access rights: T, P and D are independently grantable and compose freely.
    return True, ""


def build_compat_graph(jobs: list[Job]) -> dict[str, set[str]]:
    idx = {j.id: j for j in jobs}
    g = {j.id: set() for j in jobs}
    for a, b in itertools.combinations(jobs, 2):
        ok, _ = pairwise_compatible(a, b)
        if ok:
            g[a.id].add(b.id)
            g[b.id].add(a.id)
    return g


def bundle_valid(bundle: list[Job], g: dict[str, set[str]]) -> bool:
    """A bundle is a clique in the compatibility graph, closed under pairings."""
    ids = {j.id for j in bundle}
    for a, b in itertools.combinations(bundle, 2):
        if b.id not in g[a.id]:
            return False
    for j in bundle:                      # every parent drags its companions in
        if not set(j.companions) <= ids:
            return False
        if j.parent_id is not None and j.parent_id not in ids:
            return False
        if not set(j.after) <= ids:       # in-block precedence must be satisfiable
            return False
    return True


# ============================================================================
# 4. BUNDLE ENUMERATION  (production: blockplan/bundles.py)
# ============================================================================

# DECL: a block covers a limited stretch of line. Jobs further apart than this
#       are not worth bundling even if nothing forbids it — the work parties
#       cannot be supervised as one block. This single parameter is what keeps
#       the compatibility graph sparse and the enumeration tractable.
MAX_SPAN_KM = 8.0


def enumerate_bundles(jobs: list[Job], max_size: int = 5,
                      max_span_km: float = MAX_SPAN_KM,
                      cap_per_section: int | None = None
                      ) -> list[tuple[str, ...]]:
    """Bounded-size cliques of the compatibility graph, per section-line.

    NOT itertools.combinations. Enumerating all C(n,k) subsets and testing each
    is O(n^k) and dies at ~60 jobs per section; we measured it. Instead we grow
    cliques by extension: a bundle can only be extended by a job adjacent to
    *every* current member, so the recursion follows the graph's real structure
    and costs O(number of cliques), not O(number of subsets).

    Two prunes make the graph sparse enough for that to be cheap:
      1. jobs in different section-lines are never adjacent (hard);
      2. jobs more than max_span_km apart are not bundled (declared policy).
    """
    by_section: dict[str, list[Job]] = {}
    for j in jobs:
        by_section.setdefault(j.section_id, []).append(j)

    bundles: list[tuple[str, ...]] = []
    for sec, sec_jobs in by_section.items():
        sec_jobs = sorted(sec_jobs, key=lambda j: (j.km_from, j.id))
        idx = {j.id: j for j in sec_jobs}
        g: dict[str, set[str]] = {j.id: set() for j in sec_jobs}
        for a, b in itertools.combinations(sec_jobs, 2):
            if abs(a.km_from - b.km_from) > max_span_km and not related(a, b):
                continue
            ok, _ = pairwise_compatible(a, b)
            if ok:
                g[a.id].add(b.id)
                g[b.id].add(a.id)

        found: list[tuple[str, ...]] = []

        def extend(clique: list[str], cands: list[str]) -> None:
            if len(clique) >= 1:
                members = [idx[i] for i in clique]
                if bundle_valid(members, g):
                    found.append(tuple(sorted(clique)))
            if len(clique) == max_size:
                return
            for pos, v in enumerate(cands):
                # span prune on the whole clique, not just pairs
                kms = [idx[i].km_from for i in clique] + [idx[v].km_from]
                if max(kms) - min(kms) > max_span_km:
                    continue
                nxt = [u for u in cands[pos + 1:] if u in g[v]]
                extend(clique + [v], nxt)

        order = [j.id for j in sec_jobs]
        for pos, v in enumerate(order):
            extend([v], [u for u in order[pos + 1:] if u in g[v]])

        if cap_per_section is not None and len(found) > cap_per_section:
            # keep the bundles that retire the most work per block
            found.sort(key=lambda b: -sum(idx[i].dur_mean for i in b))
            found = found[:cap_per_section]
        bundles.extend(found)

    return sorted(set(bundles))


# ============================================================================
# 5. TRAFFIC DISRUPTION COST  (production: blockplan/traffic.py)
# ============================================================================

def traffic_cost(section: Section, start: int, length: int,
                 trains: list[Train], tail_min: int = 240) -> tuple[float, float, int]:
    """Deterministic priority-queue model of a block's effect on train running.

    Standard cumulative-arrivals / cumulative-service queueing. Trains scheduled
    into the section during the block wait; after the block the line drains at
    its normal headway, so delay spills past the block end. Controllers regulate
    by priority, so the queue is served highest-weight-first.

    Returns (weighted_train_minutes, raw_train_minutes, trains_affected).
    """
    end = start + length
    horizon = end + tail_min
    pool = sorted(
        [t for t in trains
         if t.section_id == section.id and start <= t.sched_min < horizon],
        key=lambda t: t.sched_min)
    if not pool:
        return 0.0, 0.0, 0

    # Service headway over time: zero throughput on a blocked single line;
    # degraded throughput when one line of a double line is blocked.
    def headway_at(t: int) -> float:
        if start <= t < end:
            return math.inf if section.is_single else section.headway_min * section.degraded_factor
        return section.headway_min

    waiting: list[Train] = []
    served: dict[str, int] = {}
    ptr = 0
    t = start
    while len(served) < len(pool) and t < horizon + 720:
        while ptr < len(pool) and pool[ptr].sched_min <= t:
            waiting.append(pool[ptr]); ptr += 1
        if not waiting:
            if ptr < len(pool):
                t = pool[ptr].sched_min
                continue
            break
        h = headway_at(t)
        if math.isinf(h):
            t = end
            continue
        waiting.sort(key=lambda tr: (-TRAIN_WEIGHT[tr.klass], tr.sched_min))
        tr = waiting.pop(0)
        served[tr.id] = t
        t += int(round(h))

    weighted = raw = 0.0
    affected = 0
    for tr in pool:
        d = max(0, served.get(tr.id, horizon) - tr.sched_min)
        if d > 0:
            affected += 1
        raw += d
        weighted += TRAIN_WEIGHT[tr.klass] * d
    return weighted, raw, affected


# ============================================================================
# 6. HAND-BACK RELIABILITY  (production: blockplan/reliability.py)
# ============================================================================

def _lognormal_params(mean: float, sd: float) -> tuple[float, float]:
    sigma = math.sqrt(math.log(1.0 + (sd / mean) ** 2))
    mu = math.log(mean) - 0.5 * sigma ** 2
    return mu, sigma


def reliability_mc(bundle: list[Job], block_len: int, n: int = 4000,
                   rng=RNG) -> float:
    """P(all three departmental hand-back chains finish inside the block).

    Structure (RULE): there is no single person-in-charge; each department
    closes independently and the block ends at the maximum of the chains.
    Within a department, that department's jobs in the bundle run in sequence.
    Cross-department 'must follow' pairings add the predecessor's time to the
    successor's chain.
    """
    # SORTED, not a bare set. Python randomises string hashing per process, so
    # `{j.dept for j in bundle}` iterates in a different order in every run; the
    # closing-chain draws below then consume the RNG stream in a different order
    # and the reliability of an identical bundle moves between runs. That single
    # missing sort was why this benchmark was not reproducible.
    depts = sorted({j.dept for j in bundle})
    n_dep = len(depts)
    infl = 1.0 + KAPPA * (n_dep - 1)          # DECL
    extra_close = LAMBDA_CLOSE * (n_dep - 1)  # DECL

    samples = {}
    for j in bundle:
        mu, sg = _lognormal_params(j.dur_mean, j.dur_sd * infl)
        samples[j.id] = rng.lognormal(mu, sg, n)

    chains = {d: np.zeros(n) for d in depts}
    for j in bundle:
        chains[j.dept] += samples[j.id]
    # cross-department precedence: a successor cannot start until its
    # predecessor is done, so the predecessor's time enters both chains.
    for j in bundle:
        for pid in j.after:
            pred = next((p for p in bundle if p.id == pid), None)
            if pred is not None and pred.dept != j.dept:
                chains[j.dept] += samples[pid]

    for d in depts:
        cm, csd = CLOSING[d]
        mu, sg = _lognormal_params(cm + extra_close, csd * infl)
        chains[d] += rng.lognormal(mu, sg, n)

    total = np.max(np.vstack([chains[d] for d in depts]), axis=0)
    return float(np.mean(total <= block_len))


def reliability_closed_form(bundle: list[Job], block_len: int) -> float:
    """Normal approximation. Same structure, closed form, for explanation.

    R = product over departments of Phi((L - M_d) / S_d).
    Every department you add multiplies in another factor below 1 — which is
    the frontier, visible in one line of algebra.
    """
    from math import erf, sqrt
    # SORTED, not a bare set. Python randomises string hashing per process, so
    # `{j.dept for j in bundle}` iterates in a different order in every run; the
    # closing-chain draws below then consume the RNG stream in a different order
    # and the reliability of an identical bundle moves between runs. That single
    # missing sort was why this benchmark was not reproducible.
    depts = sorted({j.dept for j in bundle})
    n_dep = len(depts)
    infl = 1.0 + KAPPA * (n_dep - 1)
    extra_close = LAMBDA_CLOSE * (n_dep - 1)
    out = 1.0
    for d in depts:
        m = sum(j.dur_mean for j in bundle if j.dept == d) + CLOSING[d][0] + extra_close
        v = sum((j.dur_sd * infl) ** 2 for j in bundle if j.dept == d) + (CLOSING[d][1] * infl) ** 2
        for j in bundle:
            if j.dept != d:
                continue
            for pid in j.after:
                pred = next((p for p in bundle if p.id == pid), None)
                if pred is not None and pred.dept != d:
                    m += pred.dur_mean
                    v += (pred.dur_sd * infl) ** 2
        z = (block_len - m) / math.sqrt(v)
        out *= 0.5 * (1.0 + erf(z / sqrt(2)))
    return out


# DECL: what an overrun costs, per expected minute of overrun, in the same
#       weighted-train-minute currency as the traffic cost.
OVERRUN_RATE = 3.0


def expected_overrun_cost(bundle: list[Job], block_len: int, n: int = 4000,
                          rng=RNG) -> float:
    # SORTED, not a bare set. Python randomises string hashing per process, so
    # `{j.dept for j in bundle}` iterates in a different order in every run; the
    # closing-chain draws below then consume the RNG stream in a different order
    # and the reliability of an identical bundle moves between runs. That single
    # missing sort was why this benchmark was not reproducible.
    depts = sorted({j.dept for j in bundle})
    n_dep = len(depts)
    infl = 1.0 + KAPPA * (n_dep - 1)
    extra_close = LAMBDA_CLOSE * (n_dep - 1)
    chains = {d: np.zeros(n) for d in depts}
    samples = {}
    for j in bundle:
        mu, sg = _lognormal_params(j.dur_mean, j.dur_sd * infl)
        samples[j.id] = rng.lognormal(mu, sg, n)
        chains[j.dept] += samples[j.id]
    for j in bundle:
        for pid in j.after:
            pred = next((p for p in bundle if p.id == pid), None)
            if pred is not None and pred.dept != j.dept:
                chains[j.dept] += samples[pid]
    for d in depts:
        cm, csd = CLOSING[d]
        mu, sg = _lognormal_params(cm + extra_close, csd * infl)
        chains[d] += rng.lognormal(mu, sg, n)
    total = np.max(np.vstack([chains[d] for d in depts]), axis=0)
    return float(np.mean(np.maximum(0.0, total - block_len))) * OVERRUN_RATE


# ============================================================================
# 7. WINDOW GENERATION  (production: blockplan/windows.py)
# ============================================================================

def generate_windows(sections: list[Section], trains: list[Train], days: int,
                     grid: int = 30, keep_per_day: int = 6) -> list[Window]:
    """Candidate block opportunities, priced, then pruned to the cheapest few.

    This is the 'supply map': for every section-line and day, where does the
    timetable leave capacity, and what does taking it cost.
    """
    out: list[Window] = []
    for sec in sections:
        for day in range(days):
            cands = []
            for length in ALLOWED_BLOCK_LENGTHS:
                for start in range(0, 24 * 60 - length + 1, grid):
                    wc, raw, aff = traffic_cost(sec, start, length, trains)
                    cands.append((wc, sec, day, start, length))
            # keep the cheapest few per (section, day, length) class
            for length in ALLOWED_BLOCK_LENGTHS:
                same = sorted([c for c in cands if c[4] == length])[:keep_per_day]
                for wc, s, d, st, ln in same:
                    out.append(Window(
                        id=f"W-{s.id}-{d}-{st}-{ln}", section_id=s.id, day=d,
                        start_min=st, length=ln, traffic_cost=wc))
    return out


# ============================================================================
# 8. COLUMN CONSTRUCTION  (production: blockplan/columns.py)
# ============================================================================

def build_columns(jobs: list[Job], bundles: list[tuple[str, ...]],
                  windows: list[Window], theta: float = THETA,
                  reliability_required: bool = True,
                  max_windows_per_bundle_day: int = 3,
                  mc_samples: int = 4000) -> list[Column]:
    """One column per (bundle, window) that is admissible.

    Two economies keep this cheap:
      - reliability depends only on (bundle, block length), never on which
        window, so it is computed once per pair and cached. This is why the
        chance constraint costs nothing at solve time.
      - for each bundle and day we keep only the cheapest few windows; a plan
        would never choose a dearer window of the same length on the same day.
    """
    idx = {j.id: j for j in jobs}
    win_by_sec_day: dict[tuple[str, int, int], list[Window]] = {}
    for w in windows:
        win_by_sec_day.setdefault((w.section_id, w.day, w.length), []).append(w)
    for k in win_by_sec_day:
        win_by_sec_day[k].sort(key=lambda w: w.traffic_cost)

    cols: list[Column] = []
    rel_cache: dict[tuple[tuple[str, ...], int], tuple[float, float]] = {}
    days = sorted({w.day for w in windows})
    lengths = sorted({w.length for w in windows})
    for b in bundles:
        bj = [idx[i] for i in b]
        sec = bj[0].section_id
        latest = min(j.due_day for j in bj)
        for length in lengths:
            key = (b, length)
            if key not in rel_cache:
                rel_cache[key] = (reliability_mc(bj, length, n=mc_samples),
                                  expected_overrun_cost(bj, length, n=mc_samples))
            rel, over = rel_cache[key]
            if reliability_required and rel < theta:
                continue
            for day in days:
                if day > latest:
                    continue
                for w in win_by_sec_day.get((sec, day, length),
                                            [])[:max_windows_per_bundle_day]:
                    cols.append(Column(
                        id=f"C{len(cols)}", job_ids=b, window=w,
                        reliability=rel, exp_overrun_cost=over,
                        total_cost=w.traffic_cost + over))
    return cols


# ============================================================================
# 9. SELECTION  (production: blockplan/solver.py)
# ============================================================================

def deferral_penalty(j: Job, horizon_days: int) -> float:
    """DECL: what it costs to leave a job undone across the horizon.

    Monotone in urgency; deliberately simple. A fitted survival model would be
    more defensible with real failure data and is out of MVP scope.
    """
    slack = max(0, j.due_day - horizon_days)
    return j.criticality * 100.0 / (1.0 + slack)


def solve(jobs: list[Job], columns: list[Column], sections: list[Section],
          horizon_days: int, grid: int = 30,
          time_limit_s: float = 30.0, force_job: str | None = None,
          deterministic_limit: float | None = 60.0) -> dict:
    """Select the plan.

    `deterministic_limit` is CP-SAT's machine-independent work budget. It exists
    because a wall-clock limit is NOT reproducible: with several workers racing,
    the same instance solved twice on the same machine returned 140 blocks once
    and 137 the next time, and a slower or busier machine would differ again.
    A benchmark whose numbers move between runs cannot support any claim made
    from it. With a deterministic budget the same input yields the same plan
    everywhere, and `time_limit_s` stays only as a wall-clock safety cap so a
    pathological instance cannot hang. Set deterministic_limit=None to go back
    to wall-clock-only behaviour.
    """
    idx = {j.id: j for j in jobs}
    model = cp_model.CpModel()
    x = {c.id: model.NewBoolVar(c.id) for c in columns}

    # (a) each job appears in at most one selected column
    cols_with: dict[str, list[Column]] = {j.id: [] for j in jobs}
    for c in columns:
        for jid in c.job_ids:
            cols_with[jid].append(c)
    for jid, cs in cols_with.items():
        if cs:
            model.Add(sum(x[c.id] for c in cs) <= 1)

    # optional: force one job into the plan, to price its refusal
    if force_job is not None and cols_with.get(force_job):
        model.Add(sum(x[c.id] for c in cols_with[force_job]) == 1)

    # (b) no two blocks overlap in time on the same section-line
    slots: dict[tuple[str, int, int], list[Column]] = {}
    for c in columns:
        w = c.window
        for t in range(w.start_min, w.end_min, grid):
            slots.setdefault((w.section_id, w.day, t), []).append(c)
    for key, cs in slots.items():
        if len(cs) > 1:
            model.Add(sum(x[c.id] for c in cs) <= 1)

    # (c) an exclusive resource cannot be in two places in the same slot
    res_slots: dict[tuple[str, int, int], list[Column]] = {}
    for c in columns:
        w = c.window
        res = set()
        for jid in c.job_ids:
            res |= set(idx[jid].resources)
        # sorted for the same reason as the department sets: an unordered set of
        # strings makes the CP-SAT model's constraints arrive in a different
        # order each process, and the solver then breaks ties differently, so the
        # same instance yields a different (equally optimal) plan between runs.
        for r in sorted(res):
            for t in range(w.start_min, w.end_min, grid):
                res_slots.setdefault((r, w.day, t), []).append(c)
    for key, cs in res_slots.items():
        if len(cs) > 1:
            model.Add(sum(x[c.id] for c in cs) <= 1)

    # objective: traffic + expected overrun for what we do,
    #            deferral risk for what we don't. One currency throughout.
    terms = []
    for c in columns:
        terms.append(int(round(c.total_cost * 10)) * x[c.id])
    for j in jobs:
        if j.is_companion or not cols_with[j.id]:
            continue
        pen = int(round(deferral_penalty(j, horizon_days) * 10))
        done = model.NewBoolVar(f"done_{j.id}")
        model.Add(sum(x[c.id] for c in cols_with[j.id]) == done)
        terms.append(pen * (1 - done))
    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    if deterministic_limit is not None:
        # Reproducible mode. This instance is highly degenerate -- the bundle-only
        # relaxation has thousands of distinct plans at exactly the same optimal
        # objective -- so with a portfolio of workers racing, "the" optimal plan
        # returned is whichever worker proved it first, and the block count and
        # cross-department share move between runs even though the objective does
        # not. A single worker plus a deterministic work budget removes both
        # sources of drift. It costs wall-clock time, and that is the right trade
        # for numbers we intend to quote.
        solver.parameters.max_deterministic_time = deterministic_limit
        solver.parameters.num_workers = 1
    else:
        solver.parameters.num_workers = 8
    solver.parameters.random_seed = 1
    t0 = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - t0

    chosen = [c for c in columns if solver.Value(x[c.id])]
    placed = {jid for c in chosen for jid in c.job_ids}
    deferred = [j.id for j in jobs if not j.is_companion and j.id not in placed]
    return {
        "status": solver.StatusName(status),
        "objective": solver.ObjectiveValue() / 10.0,
        "blocks": sorted(chosen, key=lambda c: (c.window.day, c.window.start_min)),
        "deferred": deferred,
        "seconds": elapsed,
        "deterministic_time": solver.ResponseProto().deterministic_time,
        "n_columns": len(columns),
    }


# ============================================================================
# 10. REFUSAL EXPLANATION  (production: blockplan/explain.py)
# ============================================================================

def explain_refusal(job: Job, jobs: list[Job], columns: list[Column],
                    windows: list[Window], sections: list[Section],
                    horizon_days: int, baseline_objective: float,
                    theta: float = THETA) -> dict:
    """Why isn't this job in the plan, and what would it take to get it in?

    Two genuinely different answers, and conflating them is the mistake:

      INFEASIBLE  no admissible column exists at all. The explanation is which
                  filter killed it — a Class D negation, or reliability below
                  theta at every allowed block length.

      OUTBID      admissible columns exist; the optimiser chose not to take one
                  because the cost of doing so exceeded the cost of deferring.
                  The honest explanation is the price: force it in and report
                  how much worse the whole plan gets, and what it displaces.
    """
    idx = {j.id: j for j in jobs}
    mine = [c for c in columns if job.id in c.job_ids]

    if not mine:
        levers = []
        if job.needs_train_movements:
            levers.append({"lever": "none available", "reliability": None,
                           "verdict": "activity requires train movements; it "
                                      "cannot be done inside a traffic block"})
        if job.needs_live_ohe:
            levers.append({"lever": "none available", "reliability": None,
                           "verdict": "activity requires live OHE; it cannot be "
                                      "done inside a power block"})
        bundle = [job] + [idx[c] for c in job.companions]
        for length in list(ALLOWED_BLOCK_LENGTHS) + [EXCEPTIONAL_LENGTH]:
            r = reliability_mc(bundle, length)
            levers.append({
                "lever": f"take a {length}-minute block",
                "reliability": round(r, 3),
                "verdict": "would be admissible" if r >= theta
                           else f"P(hand back on time) below theta={theta}",
            })
        return {"job": job.id, "verdict": "INFEASIBLE",
                "candidate_columns": 0, "levers": levers}

    # OUTBID: price the forced insertion.
    forced = solve(jobs, columns, sections, horizon_days, force_job=job.id)
    if forced["status"] in ("OPTIMAL", "FEASIBLE"):
        chosen = next((c for c in forced["blocks"] if job.id in c.job_ids), None)
        delta = forced["objective"] - baseline_objective
        return {
            "job": job.id, "verdict": "OUTBID",
            "candidate_columns": len(mine),
            "price_of_forcing": round(delta, 1),
            "would_go_in": None if chosen is None else {
                "day": chosen.window.day,
                "start": chosen.window.start_min,
                "length": chosen.window.length,
                "with": [j for j in chosen.job_ids if j != job.id],
                "reliability": round(chosen.reliability, 3),
                "traffic_cost": round(chosen.window.traffic_cost, 1),
            },
            "displaced": sorted(set(forced["deferred"]) - {job.id}),
            "cheapest_admissible_columns": sorted(
                ({"day": c.window.day, "start": c.window.start_min,
                  "len": c.window.length, "R": round(c.reliability, 3),
                  "traffic": round(c.window.traffic_cost, 1),
                  "bundle": list(c.job_ids)} for c in mine),
                key=lambda d: d["traffic"])[:3],
        }
    return {"job": job.id, "verdict": "INFEASIBLE_WHEN_FORCED",
            "candidate_columns": len(mine), "levers": []}


# ============================================================================
# 11. BASELINES  (production: blockplan/baselines.py)
# ============================================================================

def baseline_department_wise(jobs, bundles, windows, sections, horizon_days,
                             *, reliability_required):
    """Department-wise planning: each department plans alone, in a fixed order.

    `reliability_required` is deliberately keyword-only and has NO default,
    because the two settings are two different baselines and conflating them was
    a real error in this project:

      False -> B0, current departmental practice. Each department takes the
               cheapest window it can get for its own work. Nobody computes a
               hand-back probability, because nobody does today.
      True  -> B1, department-wise planning that keeps our chance constraint.
               This is NOT current practice; it is our method with cross-
               department bundling switched off.

    Reading B0 -> B1 isolates the effect of the reliability filter alone, and
    B1 -> OURS isolates the effect of integrated cross-department bundling.
    A default here would let a caller silently report B1 as "current practice".
    """
    used_slots: set[tuple[str, int, int]] = set()
    chosen: list[Column] = []
    placed: set[str] = set()
    for dept in DEPTS:
        dept_jobs = [j for j in jobs if j.dept == dept and not j.is_companion]
        ids = {j.id for j in dept_jobs}
        # single-department bundles only
        b = [x for x in bundles
             if set(x) <= ids | {c for j in dept_jobs for c in j.companions}]
        cols = build_columns(jobs, b, windows,
                             reliability_required=reliability_required)
        cols.sort(key=lambda c: c.total_cost)
        for c in cols:
            if set(c.job_ids) & placed:
                continue
            w = c.window
            keys = {(w.section_id, w.day, t)
                    for t in range(w.start_min, w.end_min, 30)}
            if keys & used_slots:
                continue
            chosen.append(c); used_slots |= keys; placed |= set(c.job_ids)
    return chosen, placed


def baseline_fixed_calendar(jobs, windows, sections, horizon_days,
                            fixed_start=600, fixed_len=240):
    """B2 — current practice: a fixed daily corridor block, filled by due date."""
    chosen: list[Column] = []
    placed: set[str] = set()
    idx = {j.id: j for j in jobs}
    real = sorted([j for j in jobs if not j.is_companion],
                  key=lambda j: j.due_day)
    for day in range(horizon_days):
        for sec in sections:
            w = next((w for w in windows
                      if w.section_id == sec.id and w.day == day
                      and w.length == fixed_len), None)
            if w is None:
                continue
            # fill greedily with same-department jobs by due date, no reliability check
            pack: list[Job] = []
            for j in real:
                if j.id in placed or j.section_id != sec.id or j.due_day < day:
                    continue
                cand = pack + [j] + [idx[c] for c in j.companions]
                if sum(x.dur_mean for x in cand) > fixed_len:
                    continue
                g = build_compat_graph(cand)
                if not bundle_valid(cand, g):
                    continue
                pack = cand
            if pack:
                ids = tuple(sorted(p.id for p in pack))
                rel = reliability_mc(pack, fixed_len)
                over = expected_overrun_cost(pack, fixed_len)
                chosen.append(Column(f"B2-{sec.id}-{day}", ids, w, rel, over,
                                     w.traffic_cost + over))
                placed |= set(ids)
    return chosen, placed


def baseline_greedy_earliest(jobs, bundles, windows, horizon_days):
    """B3 — every job into the earliest feasible window, no bundling."""
    singles = [b for b in bundles if len({jid.split('c')[0] for jid in b}) == 1]
    cols = build_columns(jobs, singles, windows, reliability_required=False)
    cols.sort(key=lambda c: (c.window.day, c.window.start_min))
    used: set[tuple[str, int, int]] = set()
    chosen, placed = [], set()
    for c in cols:
        if set(c.job_ids) & placed:
            continue
        w = c.window
        keys = {(w.section_id, w.day, t)
                for t in range(w.start_min, w.end_min, 30)}
        if keys & used:
            continue
        chosen.append(c); used |= keys; placed |= set(c.job_ids)
    return chosen, placed


# ============================================================================
# 12. EVALUATION  (production: blockplan/evaluate.py)
# ============================================================================

def evaluate(name: str, chosen: list[Column], jobs: list[Job]) -> dict:
    real = [j for j in jobs if not j.is_companion]
    idx = {j.id: j for j in jobs}
    placed = {jid for c in chosen for jid in c.job_ids}
    cross = 0
    for c in chosen:
        if len({idx[j].dept for j in c.job_ids}) > 1:
            cross += 1
    util = np.mean([sum(idx[j].dur_mean for j in c.job_ids) / c.window.length
                    for c in chosen]) if chosen else 0.0
    done = len([j for j in real if j.id in placed])
    tc = sum(c.window.traffic_cost for c in chosen)
    return {
        "method": name,
        "blocks": len(chosen),
        "jobs_done": done,
        "jobs_deferred": len([j for j in real if j.id not in placed]),
        "traffic_cost": round(tc, 1),
        "traffic_per_job": round(tc / done, 1) if done else float("inf"),
        "exp_overrun_cost": round(sum(c.exp_overrun_cost for c in chosen), 1),
        "cross_dept_blocks": cross,
        "cross_dept_share": round(cross / len(chosen), 3) if chosen else 0.0,
        # Two decimals, not three. These are Monte Carlo estimates: at the 1500
        # samples used for the benchmark the standard error of a single block's
        # reliability near 0.9 is about 0.008, so the third decimal is noise and
        # printing it implies a precision the method does not have. They are also
        # MODELLED probabilities under the declared duration and closing-chain
        # distributions, not historically calibrated frequencies.
        "min_reliability": round(min([c.reliability for c in chosen], default=1.0), 2),
        "mean_reliability": round(float(np.mean([c.reliability for c in chosen]))
                                  if chosen else 1.0, 2),
        "block_utilisation": round(float(util), 3),
    }
