"""A stand-in for TMS / SMMS / TDMS, so the ingestion path can be shown running.

    python -m blockplan_ingest.mock_systems --port 8100
    python -m blockplan_ingest.mock_systems --serve-dir <feed dir> --port 8100

    GET /tms/work-orders      GET /smms/work-orders     GET /tdms/work-orders
    GET /health

A DEVELOPMENT AND DEMONSTRATION TOOL. It is not imported by the backend, not
started by run.py, and not a dependency of anything. The packaged app must keep
working with no network at all, so nothing in the planning path may ever
require this to be running -- the file-based feed is the real integration
surface, and this only puts an HTTP hop in front of the same JSON.

WHAT IT IS NOT. It does not emulate a real TMS, SMMS or TDMS. It serves the
work orders in blockplan_ingest's own contract format, over three URLs named
after those systems, so a demonstration can show data arriving over HTTP
instead of being read from disk. Calling it "a TMS simulator" would overstate
it by a wide margin: the contract is ours (see contract.py), and so is this.

WHY IT EXISTS AT ALL. "Where do you get your maintenance data?" is the first
question this project gets asked. The honest answer is a contract plus an
adapter, and both are testable without a server -- but a server makes the
answer visible in ten seconds rather than in a code review.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Mapping

from .contract import SOURCE_SYSTEMS
from .feeds import FEED_FILES

#: URL path -> source system.
ROUTES = {f"/{system.lower()}/work-orders": system for system in SOURCE_SYSTEMS}


def build_default_feed(destination: str) -> str:
    """Publish the frozen dataset as work orders, so the server has something.

    The same export blockplan_ingest.verify uses, which is what makes a
    demonstration meaningful: the plan produced from these URLs is the
    reference plan, not an approximation of it.
    """
    import csv

    from blockplan_service import paths

    from .feeds import demand_to_feed_records, write_feed_directory

    with open(os.path.join(paths.PROCESSED_DIR, "jobs.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    write_feed_directory(demand_to_feed_records(rows), destination)
    return destination


class _Handler(BaseHTTPRequestHandler):
    feed_dir: str = ""

    def do_GET(self) -> None:                     # noqa: N802  (stdlib naming)
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/health":
            return self._json(200, {
                "status": "ok",
                "systems": list(SOURCE_SYSTEMS),
                "serving": self.feed_dir,
                "notice": "Mock endpoints. Not a real TMS/SMMS/TDMS, and not "
                          "an emulation of one -- see mock_systems.py.",
            })
        if path == "/":
            return self._json(200, {"endpoints": sorted(ROUTES) + ["/health"]})

        system = ROUTES.get(path)
        if system is None:
            return self._json(404, {"error": f"no such endpoint: {path}",
                                    "endpoints": sorted(ROUTES)})
        try:
            with open(os.path.join(self.feed_dir, FEED_FILES[system]),
                      encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return self._json(503, {
                "error": f"no {system} feed published in {self.feed_dir}"})
        return self._json(200, payload)

    def _json(self, status: int, body: Mapping[str, Any]) -> None:
        encoded = json.dumps(body, indent=1).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: Any) -> None:
        # One line per request, on stdout, so a demo can show the pull happening.
        sys.stdout.write(f"[mock-systems] {self.address_string()} "
                         f"{fmt % args}\n")
        sys.stdout.flush()


def serve(feed_dir: str, port: int = 8100, host: str = "127.0.0.1") -> HTTPServer:
    """Start the server. Returns it; the caller owns shutdown."""
    handler = type("_Bound", (_Handler,), {"feed_dir": feed_dir})
    return HTTPServer((host, port), handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Mock TMS/SMMS/TDMS endpoints for demonstration.")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback by default; this serves no real system")
    ap.add_argument("--serve-dir",
                    help="publish an existing feed directory instead of "
                         "exporting the frozen dataset")
    args = ap.parse_args(argv)

    if args.serve_dir:
        feed_dir = args.serve_dir
        if not os.path.isdir(feed_dir):
            print(f"no such directory: {feed_dir}", file=sys.stderr)
            return 2
    else:
        feed_dir = build_default_feed(
            os.path.join(tempfile.mkdtemp(prefix="blockplan-mock-"), "feed"))
        print(f"published the frozen dataset as work orders in {feed_dir}")

    server = serve(feed_dir, args.port, args.host)
    base = f"http://{args.host}:{args.port}"
    print(f"mock TMS/SMMS/TDMS on {base}")
    for path in sorted(ROUTES):
        print(f"  {base}{path}")
    print("\nThese are NOT real Indian Railways systems and do not emulate "
          "them.\nThey serve this project's own ingestion contract over HTTP.")
    print("\nCtrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
