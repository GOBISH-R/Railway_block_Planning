# BlockPlan frontend — Phase 3

React + TypeScript + Vite. Built against `API_CONTRACT.md`, not against the
backend's source — the two are only coupled through that document and the
Pydantic/TypeScript types on either side of it.

## What is here

```
src/
  api/          typed client + types mirroring API_CONTRACT.md field-for-field
  state/        usePlanningState -- the one piece of shared state every view needs
  styles/       design tokens (colour, type, spacing) + global reset
  components/
    Shell/      app chrome: brand, primary nav
    Timeline/   the Plan view -- controls, summary strip, the SVG timeline, deferred list
    Corridor/   linear corridor strip, map inset, demand table
    WhyPanel/   the explanation slide-over: chain diagram, block/job views
    Evidence/   comparison tables + cost-vs-reliability scatter
    shared/     badges, buttons, form fields, loading/error/empty states
```

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
npm test         # vitest -- pure-function and API-client unit tests
npm run lint     # oxlint
npx tsc --noEmit # type-check
npm run build    # production build
```

Component-level UI is verified by hand in the browser (screenshotted against
the real backend) rather than with a mocked-DOM test suite for every
component; the pure functions that could silently drift (corridor km
placement, timeline geometry, traffic bucketing, API error handling) have
focused unit tests.

## Design decisions worth knowing

**No component library, no charting library, no map library.** Four
hand-drawn SVG visualisations (timeline, corridor strip, chain diagram,
scatter) plus plain HTML tables. A component library would fight the custom
SVG timeline, which is the one thing that has to be exactly right; a charting
library is not worth its weight for one scatter plot; a map library needs a
tile server, which does not work offline.

**One theme, no dark mode.** Projector contrast is the only display
consideration that matters for a demo; light-with-strong-contrast serves that
better than a toggle nobody asked for.

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
