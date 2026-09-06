# BlockPlan — demo pack

SIH 2026, PS 26027. Everything here was rehearsed against the running
packaged app (`python run.py`, `http://localhost:8000`) on 2026-09-06, and
every number quoted was read off the screen or the frozen CSVs, not from
memory.

**Read §5 (readiness checklist) before presenting.** Two items there need a
decision that is not a code change.

---

## 1. Demo flow — 6 min 20 s

The project memory's §19 script, corrected where rehearsal showed the script
promised something the software does not actually do. Corrections are marked
**[CORRECTED]** with the reason.

| Time | Screen | What you do | What you say |
|---|---|---|---|
| 0:00 | **Corridor & Demand** | Land here. Point along the strip. | "Track, signalling and overhead-line staff all need the same line closed. Every closure delays trains. Today each department asks separately, and a substantial share of blocks are refused or handed back late." |
| 0:40 | Corridor & Demand | Click **ENGG**, then **SNT**, then **TRD** in turn. | "Three departments. The same kilometres light up three times. That is the competition for one scarce resource." |
| 1:15 | **Plan** | Switch to Plan. Point at the shading *between* the blocks. | "This is the real published timetable — 2,568 real movements. The pale banding is traffic density. The white space is all the capacity that exists." |
| 1:45 | Plan | Drag **θ to 0.97**, press **Re-plan**. Let the ~3 s run. | "That is a constraint solver proving optimality over sixteen thousand candidate decisions." |
| 2:20 | Plan → **Why** | Click a three-department block — **aim for B0010, day 0, KEY→KNNT UP, 10:00** (see targets below). | "Tamping compels overhead-line and signalling work — that is a rule, not our idea. What is ours is putting them in one block and proving it still hands back on time." |
| 3:10 | Why panel | Point at the three chains against the dashed envelope. | "The block ends when the last of three independent departments finishes. No single person owns the possession in India. That is why this is a probability, not a deadline." |
| 3:50 | Plan → **Why** | Click a deferred job. Show INFEASIBLE. Then an OUTBID one. | "Not a black box. This one is infeasible at every permitted block length. That one was outbid — and here is exactly what forcing it in would cost, and what it would displace." |
| 4:30 | Plan | Switch scenario to **Maintenance Backlog**, Re-plan. Instant. | "Now 340 jobs. It defers 152 and tells you which — that is a capacity answer the division does not currently have." |
| 5:10 | **Evidence** | Point at the **worst block** column, not the averages. | "Against five baselines on the same instance. And scored against thirty independent executions the planner never saw: the greedy plan's worst block handed back on time zero times in thirty. Ours, twenty-eight." |
| 6:00 | Plan | Return to the plan. | "Real infrastructure, real timetable, synthetic maintenance demand — clearly labelled, because that data is not public. Reproducible from three published files and one seed." |

### Block targets — do not hunt on stage

32 of the 140 blocks are three-department. Hunting for one on a 52-row × 14-day
grid in front of judges is an unforced error. These are all on day 0–2, at
θ = 0.90, NORMAL_TRAFFIC (the state the app starts in), so they are within the
first screen-width without scrolling:

| Block | Day | Section | Start | Length | Modelled R |
|---|---|---|---|---|---|
| **B0010** | 0 | KEY→KNNT UP | 10:00 | 150 min | **0.95** |
| B0017 | 0 | DC→MVPM DN | 13:00 | 150 min | 0.94 |
| B0003 | 0 | DVBH→DC UP | 06:00 | 240 min | 1.00 |
| B0006 | 0 | BQI→LCR UP | 09:00 | 240 min | 1.00 |

**Use B0010.** Verified on screen — it is the canonical story of this whole
project in one panel:

- **Jobs:** J00016 ENGG `THROUGH_TAMPING` (62 min) → J00016c0 TRD
  `OHE_HEIGHT_ADJUSTMENT` (25 min) → J00016c1 SNT `SNT_ASSOCIATION` (15 min).
  The two companions were *derived by rule*, not requested by anyone.
- **Citation on screen:** "THROUGH_TAMPING compels TRD to perform
  OHE_HEIGHT_ADJUSTMENT immediately after it — ACTM Ch.17, due notice to OHE
  staff before any alteration to alignment or level…" That sentence is the
  pitch. Read it off the screen.
- **Chains:** ENGG Φ=1.00, SNT Φ=1.00, **TRD Φ=0.97** — TRD visibly reaches
  closest to the dashed 150-minute envelope. There is real tension to point at.
- **Modelled P(hand back within 150 min) = 0.953** against θ = 0.90.
- **Reliability by length:** 120 min → 0.617 **No**; 150 min → 0.971 Yes;
  240 min → 1.000 Yes. The *No* row is the proof the constraint bites.

Avoid the 240-minute blocks at R = 1.00 (B0003, B0006): every chain finishes
comfortably, the envelope looks over-generous, and there is nothing to point at.

If the plan has been re-planned at a different θ, block ids change. Re-plan at
θ = 0.90 first, or just click any bar striped with three colours.

**One practical note:** a 150-minute block is a ~17-pixel-wide target
(measured). It is unobstructed and responds reliably to an accurate click —
but give the page a couple of seconds to settle after loading before clicking,
since a click fired mid-load is silently swallowed. Browser zoom (Ctrl +)
should scale the whole timeline, as the layout is in CSS pixels throughout —
**try this during rehearsal**; it could not be tested from the dev
environment. The deferred-job list on the right has full-width targets and
needs no such care.

### [CORRECTED] The 1:45 / 3:10 θ beat

The original script says *"Drag θ from 0.90 to 0.97. The plan visibly thins."*
**It does not visibly thin.** Rehearsed and measured:

| θ | Blocks | Jobs done | Deferred | Traffic cost | Min R |
|---|---|---|---|---|---|
| 0.90 | 140 | 174 | 1 | 299.2 | 0.90 |
| 0.97 | 138 | 172 | **3** | **360.8** | 0.98 |
| 0.99 | 137 | 172 | 3 | 366.8 | 0.99 |

140 → 138 blocks is invisible on screen. Do **not** promise a visual change a
judge can see is not happening — that is the single fastest way to lose the
room. Narrate the **summary strip** instead, which changes dramatically and
tells a better story:

> "Watch the numbers, not the bars. Deferred work goes from one job to three.
> Traffic cost goes up twenty-one percent. And the weakest block in the whole
> plan goes from 0.90 to 0.98. Reliability is bought, not free — and the
> controller just saw the price."

### [CORRECTED] The 1:15 "no blocks yet" beat

The original script wants the Plan view showing traffic shading with no blocks
drawn. The app plans automatically on load, so that state does not exist, and
adding a hide-blocks toggle would be a control with no operational purpose.
Narrate the white space *between* the blocks instead — the point (capacity is
scarce and visible) lands identically.

### Timing measured on this machine

Cold start with warmup: ~70 s–2 min for all eight scenarios (run `python
run.py` well before you present). Live re-plan at a new θ: **~3 s**. Cached
scenario switch: **<0.1 s**. OUTBID explanation: **~4 s** (a real re-solve —
the spinner is honest, let it run).

---

## 2. Judge questions and answers

**"Where is the AI?"** — Four mechanisms, all squarely AI as the field defines
it: constraint optimisation (CP-SAT set-packing over ~16,700 candidate
columns, solved to proven optimality); combinatorial search (bounded clique
enumeration over a compatibility graph); reasoning under uncertainty (Monte
Carlo over three concurrent hand-back chains feeding a chance constraint);
and rule-based inference (mandatory-pairing expansion deriving obligations
never stated in the input). Constraint satisfaction and planning under
uncertainty are foundational AI, not a consolation prize. We call it a
constraint-optimisation and stochastic-simulation decision-support system.

**"Why no machine learning?"** — The valuable ML target is obvious: predict a
job's real duration distribution and a bundle's overrun probability from
history. That needs block-register outcome records — requested vs granted vs
actually returned, over years. That is BDMS and divisional registers. It is
not public and we do not have it. Training on our own `execution.csv` would be
circular: those realisations were drawn from the same lognormal distributions
the reliability model assumes, so a model would learn our own assumption back
and report excellent accuracy. Knowing exactly where learning would help, and
declining to fake it, is the honest answer.

**"Is this real Indian Railways data?"** — Volunteer this before they ask.
Infrastructure, stations, coordinates and train schedules are real public data
(DataMeet, CC0). Maintenance jobs, block requests, freight paths and execution
realisations are **synthetic**, generated from documented distributions and
railway rules. It is not Indian Railways maintenance data and we never
describe it as such. See §4.

**"How do you know θ = 0.90 is right?"** — We do not, and we say so. θ is a
policy parameter the division sets. That is exactly why it is a slider and not
a constant.

**"Your cross-department share is lower than some baselines."** — True: OURS
36.4% against B2's 50.5% and B4's 39.1%. Bundling only happens where the
bundle survives the reliability constraint, so a lower share is the constraint
working, not the innovation failing. B2 achieves its 50.5% by ignoring
hand-back risk entirely — its worst block hands back on time in 29 of 30
executions with a 38.7-minute overrun.

**"You lose to a baseline on traffic cost."** — Volunteer this too. B4 costs
272.8 against our 299.2. We buy minimum reliability 0.74 → 0.90 and expected
overrun 69.0 → 38.6 for that ~10% traffic premium. Reliability is bought, not
free, and we would rather show the price than hide it.

**"Would the block count change if you ran it again?"** — Yes, slightly, and
we know why. This instance is massively degenerate: we probed it, and the
optimal face contains solutions from 118 to 153 blocks at the *identical*
optimal objective. Objective, traffic cost and reliability are invariant;
block count and cross-department share are chosen by solver tie-breaking. We
quote the first three with confidence and treat the other two as indicative.

**"Is it deployed?"** — No deployment, no pilot, no endorsement. The
integration point is one loader — `PlanningContext` — which today reads frozen
CSVs and would instead read the control office application, BDMS and the WTT.

**"Why does that job get a block when it needs no protection?"** — Honest
answer: Class D jobs (needing trains running or the OHE live) are never
*bundled* with other work, which is what the compatibility engine enforces.
A single such job can still occupy a window of its own. Whether work needing
no protection should consume a block window is an operational question we have
flagged rather than quietly resolved.

---

## 3. The optimisation, in the order to explain it

1. **Expand.** Mandatory pairing rules (ACTM Ch.17, IRTMM Ch.3/Ch.5) turn one
   tamping job into tamping + OHE height adjustment + S&T association. 175
   jobs become 238. Forward chaining over a cited rule base.
2. **Enumerate.** Bounded cliques of the compatibility graph, per section-line
   — 449 bundles. Grown by extension, not `C(n,k)`, which was measured to die
   at ~60 jobs per section.
3. **Price the supply.** 11,648 candidate windows, each priced by a
   priority-queue traffic simulation against the real timetable. This is 75% of
   a cold plan and depends only on (sections, trains, horizon) — which is why
   there are exactly eight window sets in the system and why they are cached.
4. **Filter by risk.** For each (bundle, window): Monte Carlo over three
   independent departmental hand-back chains, block ends at their maximum.
   Keep only combinations with P(hand back in time) ≥ θ. 16,746 columns.
5. **Select.** CP-SAT set-packing. Each job in at most one block; no two blocks
   overlap on a section-line; an exclusive resource cannot be in two places.
   Objective in one currency throughout: traffic cost + expected overrun for
   work done, plus a deferral penalty for work not done.
6. **Explain.** Refusal is either INFEASIBLE (no admissible column — say which
   filter killed it) or OUTBID (columns exist; price the forced insertion and
   name what it displaces).

**The one-line innovation claim:** reliability-constrained cross-department
block bundling, where admissibility is decided by a chance constraint on the
maximum of independent departmental hand-back chains, with rule-mandated
companion work expanded before optimisation, and refusal explained as either
infeasibility or a priced trade.

---

## 4. Data provenance — say this before you are asked

> "Infrastructure, stations, coordinates and train schedules are real public
> data. Maintenance jobs, block requests, freight paths and execution
> realisations are SYNTHETIC. This is not Indian Railways maintenance data and
> must never be described as such."

The five-class system, enforced in code across 113 columns and 12 tables:

| Class | Meaning | What is in it |
|---|---|---|
| **A — REAL** | Real public data, as published | 27 station codes, names, coordinates; train numbers and names; published timetable stop times |
| **B — DERIVED** | Computed from real data by a documented method | Corridor topology and station ordering (discovered from real routes); section lengths (great-circle, scaled to the published 182.0 km); service class read from the operator's own train names |
| **C — RULE** | From an Indian Railways manual | The 6 mandatory pairing rules (6/6 carry a citation); protection regime per activity; block envelope options |
| **D — SYNTHETIC** | Generated from a documented distribution | **All 175 maintenance jobs**; block requests; 410 freight paths; 30 execution realisations |
| **E — ASSUMPTION** | An explicit modelling choice we made | θ, KAPPA, LAMBDA_CLOSE, closing-chain times, train priority weights, asset counts, max span km, overrun rate |

The correct one-sentence framing: *"A reproducible synthetic benchmark built
on real Indian Railway infrastructure and publicly available railway data,
with unavailable maintenance and block variables synthesised using documented
railway rules, distributions and explicit assumptions."*

Reproducible from three published files (`stations.json`, `trains.json`,
`schedules.json`, hashes recorded) and one seed (42). Freight is synthetic
because public timetables carry almost no freight — CAG Report 45/2018 Ch.3
records goods trains running "without any scheduled timing."

**Never say:** "trained AI model", "our AI predicts", "validated on Indian
Railways data", "proven 90% reliable", or any delay-reduction percentage not
from our own table.

---

## 5. Readiness checklist

### Verified working (rehearsed in the browser, against the live packaged app)

- [x] All four views render from real backend responses; no mock data anywhere
- [x] Corridor: 27 stations JTJ→ED in order, 175 job marks at true km offsets
- [x] Department filter: ENGG 79 / SNT 49 / TRD 47 = 175, matching the dataset
- [x] Plan: 140 blocks, 174 done, 1 deferred, matching `benchmark_results.csv`
- [x] Live re-plan at new θ: ~3 s, plan and all metrics update correctly
- [x] Why panel — SCHEDULED block: three chains, envelope, reliability by length, rule citations
- [x] Why panel — INFEASIBLE job: full lever table at 240/150/120 min
- [x] Why panel — OUTBID job: price 7.1, would-go-in placement, displaced job
- [x] Scenario switch to MAINTENANCE_BACKLOG: instant, 159 blocks / 152 deferred
- [x] Evidence: three frozen tables + scatter, numbers matching the CSVs
- [x] Console clean throughout; keyboard focus visible; Escape closes the panel
- [x] 106 backend tests, 28 frontend tests passing
- [x] Runs from one command on one port with no network calls at runtime

### Resolved

- [x] **B4 row disagreement — settled: the frozen CSV is authoritative.** The
      CSV was not regenerated and no benchmark was re-run. Quote B4 as
      **138 blocks / 175 done / 0 deferred / 272.8 traffic / 69.0 overrun /
      39.1% cross-dept / 0.99 mean R / 0.74 min R** — these are what the
      Evidence screen serves and therefore what a judge sees. The project
      memory §22.1's B4 row (142 / 259.8 / 79.9 / 35.9%) is **superseded; do
      not quote it.** The other five rows agree with §22.1 exactly. Full
      reasoning in `CLAUDE.md`.

### Needs a decision before submission — not a code change

- [ ] **Cross-department share is tie-break dependent.** Do not present 36.4%
      as a measured property of the method. Prepared answer is in §2.

### Must happen on the actual presentation laptop

- [ ] `pip install -r backend/requirements.txt` and `npm install` in
      `frontend/` — once, with network
- [ ] Disconnect networking, reboot, `python run.py` from cold, run the full
      demo. This has **not** been done — it cannot be done from a dev
      environment and is the one Phase 8 test still outstanding.
- [ ] Time the live re-plan on that machine. It is ~3 s here; the memory
      document's figures came from a faster machine, and CP-SAT is the part
      that varies.
- [ ] Start the server and let warmup finish **before** the session begins.

### Rehearsal

- [ ] Deliver the §1 flow out loud, timed, ten times
- [ ] Each team member can answer any §2 question
- [ ] Present to someone who has never seen it; ask them to say back what the
      innovation was. If they cannot, the demo is wrong, not them.
