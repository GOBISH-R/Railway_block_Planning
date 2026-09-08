# BlockPlan frontend

React 19 + TypeScript + Vite. Built against `API_CONTRACT.md`, not against the
backend's source — the two are only coupled through that document and the
Pydantic/TypeScript types on either side of it.

## What is here

```
src/
  api/          typed client + types mirroring API_CONTRACT.md field-for-field
  state/        usePlanningState (plan + scenario + theta) and useTheme
  styles/       design tokens (colour, type, spacing) + global reset
  components/
    Shell/      app chrome: brand, primary nav
    Overview/   the landing view -- corridor, plan and availability at a glance
    Timeline/   the Block Plan view -- controls, summary strip, SVG timeline, deferred list
    Corridor/   linear corridor strip, map inset, demand table
    WhyPanel/   the explanation slide-over: chain diagram, block/job views
    shared/     KPI cards, buttons, form fields, loading/error/empty states
```

Three destinations: Overview, Block Plan, Corridor & Demand. An earlier
revision had eight, including a benchmark comparison against five baselines.
The benchmark still exists -- it is the frozen `method_comparison.csv`, still
served by `GET /comparison` -- but it is not a screen in the planning app, so
nothing in the running product argues the method against its baselines. That
argument lives in the written evidence.

No planning or optimisation logic lives here. Every number on screen is read
from a backend response; nothing is computed by re-deriving what the
optimiser already decided.

## Setup

```
npm install
npm run dev      # http://localhost:5173, proxies /api/* to the backend on :8000
```

Run the backend first (`cd ../backend && uvicorn blockplan_api.app:app --port 8000`).
Without it, the app loads and shows a connection error rather than a blank
screen or fabricated data.

## Tests

```
npm test         # vitest -- 163 tests: pure functions, API client, components
npm run lint     # oxlint
npx tsc --noEmit # type-check
npm run build    # production build
```

Two layers, deliberately. The pure functions that could silently drift
(corridor km placement, timeline geometry, traffic bucketing, API error
handling and caching) have focused unit tests. On top of that, the components
whose failure would be invisible rather than ugly are tested against a mocked
DOM: the shell, because an unreachable view is not a visual defect; the
timeline grid, because a reliability label that fits on 24 of 140 blocks looks
fine and reads as "every block is certain"; the overview, because "no plan
computed yet" and "zero blocks" are different statements that render alike if
you are careless.

Layout and visual weight are still checked by hand in the browser against the
real backend. A test that asserts a pixel is a test that fails on a font
update.

## Design decisions worth knowing

**No component library, no charting library, no map library.** Five
hand-drawn SVG visualisations (timeline grid, timeline overview, corridor
strip, map inset, chain diagram) plus plain HTML tables. A component library
would fight the custom SVG timeline, which is the one thing that has to be
exactly right; a map library needs a tile server, which does not work offline.

**Light and dark, following the viewer.** `styles/tokens.css` defines the
palette once and redefines it under `prefers-color-scheme: dark` and an
explicit `data-theme` attribute, so the `ThemeToggle` wins in both directions
and an untouched machine follows the OS. Projector contrast was the original
argument for light-only; a hall that dims the lights is the argument against
it, and the token layer made supporting both nearly free.

**Colour is signal-derived, not decorative.** Status colours come from
railway signal aspects (green/amber/red); departments get a single small
identity chip each, never a large fill — a three-department block should read
as texture, not confetti.

**Traffic density repeats identically across every day column.** The
`/traffic` response has a minute-of-day but no day-of-week field — it is a
working timetable, which by nature repeats daily. Drawing a different profile
per day would imply data that is not there.

**Block count and cross-department share are not asserted precisely
anywhere in this UI's own logic.** Per the backend's own finding (see
`CLAUDE.md`), those two figures are chosen by solver tie-breaking on this
instance, not determined by the model. The frontend displays whatever the
backend returns without editorialising on it, but doesn't build any feature
that assumes those two numbers are stable across replans with identical
inputs.

## Known limitations

- True mobile (<640px) is a functional fallback (deferred list stacks below
  the timeline instead of beside it), not a first-class target. This is an
  operations tool for planning desks, per the project's own brief — desktop
  1280–1920px is where it is meant to be judged.
- The map inset uses a plain equirectangular projection, adequate at this
  corridor's ~1.8-degree span. It would not generalise to a much longer or
  higher-latitude corridor without a proper projection.
