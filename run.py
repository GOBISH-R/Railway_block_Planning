#!/usr/bin/env python3
"""One command, no internet: build the frontend if needed, then start the
whole system as a single process on a single port.

    python run.py

This is the Phase 8 packaging entry point. What it does NOT do: install
anything. `pip install -r backend/requirements.txt` and
`npm install` (inside frontend/) must already have been run once, WITH
network access, ahead of time -- that is a one-time setup step, not part of
"no internet at demo time". Once both are installed, this script and
everything it starts needs no network at all.

What happens on each run:
  1. If frontend/dist/ does not exist (or --rebuild is passed), build it.
     This runs `npm run build`, which needs no network -- it only reads
     already-installed node_modules.
  2. Start uvicorn with BLOCKPLAN_WARM_ON_STARTUP=1, which precomputes all
     eight scenarios' window sets and default plans before the server starts
     accepting requests. This takes a few minutes; it is meant to happen once
     before the demo starts, not live during it.
  3. Serve everything on http://localhost:8000 -- the API and the built
     frontend, from the same FastAPI process.

Test before presenting: disconnect networking, then run this from a cold
shell and open http://localhost:8000 in a browser. If anything fails to load,
it is not ready for the demo hall.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")
FRONTEND_DIST = os.path.join(FRONTEND_DIR, "dist")


def _run(cmd: list[str], cwd: str) -> None:
    print(f"$ {' '.join(cmd)}  (in {cwd})")
    result = subprocess.run(cmd, cwd=cwd, shell=(sys.platform == "win32"))
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_frontend() -> None:
    if not os.path.isdir(os.path.join(FRONTEND_DIR, "node_modules")):
        print(
            "frontend/node_modules is missing. Run `npm install` inside "
            "frontend/ once, with network access, before using this script.",
            file=sys.stderr,
        )
        sys.exit(1)
    _run(["npm", "run", "build"], cwd=FRONTEND_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true",
                        help="Rebuild the frontend even if dist/ already exists.")
    parser.add_argument("--no-warm", action="store_true",
                        help="Skip precomputing all eight scenarios at startup "
                             "(faster to start, but the first request for each "
                             "scenario then pays its full cold cost).")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.rebuild or not os.path.isdir(FRONTEND_DIST):
        build_frontend()
    else:
        print("frontend/dist/ already exists (use --rebuild to force a rebuild)")

    env = dict(os.environ)
    if not args.no_warm:
        env["BLOCKPLAN_WARM_ON_STARTUP"] = "1"
        print(
            "Warming all eight scenarios before accepting requests -- this "
            "takes a few minutes. Use --no-warm to skip (not recommended "
            "before a demo)."
        )

    print(f"\nStarting BlockPlan on http://localhost:{args.port}\n")
    cmd = [
        sys.executable, "-m", "uvicorn", "blockplan_api.app:app",
        "--host", "0.0.0.0", "--port", str(args.port),
    ]
    result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
