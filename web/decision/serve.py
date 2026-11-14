"""Local decision-support cockpit server (stdlib only, loopback, no execution endpoint).

    PYTHONPATH=src:. python3 web/decision/serve.py --port 8765

Opening the page triggers the AUTOMATIC recommendation on the current synthetic snapshot
(no scenario typed by the user). The manual X1/X2 mode posts locks to the same engine.
"Valider" is a demo review: nothing is ever sent to a hospital information system.
Every JSON document served gets an id so the page can cite the source of each figure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from hospitalos.decision_support.contracts import (  # noqa: E402
    Observation,
    Recommendation,
    ScenarioLocks,
)
from hospitalos.decision_support.planner import (  # noqa: E402
    ReviewStore,
    Settings,
    recommend,
    review,
    simulate,
)
from hospitalos.decision_support.snapshot import (  # noqa: E402
    build_snapshot,
    load_fixture_public,
    load_json,
)

HERE = Path(__file__).resolve().parent
FIXTURES = ROOT / "tests" / "decision_support" / "fixtures"
UNITS = {
    "nominal_auto": "Médecine polyvalente (fictive) — tension",
    "no_action": "Médecine polyvalente (fictive) — calme",
    "insufficient_data": "Médecine polyvalente (fictive) — planning incomplet",
}
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/decision.css": ("decision.css", "text/css; charset=utf-8"),
    "/js/decision.js": ("js/decision.js", "text/javascript; charset=utf-8"),
}


class State:
    def __init__(self) -> None:
        self.settings = Settings.default()
        self.docs: dict[str, Any] = {}
        self.recos: dict[str, Recommendation] = {}
        self.injected: dict[str, list[dict[str, Any]]] = {k: [] for k in UNITS}
        self.store = ReviewStore()
        self.events = load_json(HERE / "demo_events.json")
        self.lock = threading.Lock()

    def snapshot(self, unit: str):
        _, observations, as_of = load_fixture_public(FIXTURES / f"{unit}.json")
        observations += [Observation.model_validate(o) for o in self.injected[unit]]
        return build_snapshot(observations, as_of, self.settings.profile)

    def keep(self, reco: Recommendation) -> dict[str, Any]:
        body = reco.model_dump(mode="json")
        self.docs[reco.recommendation_id] = body
        self.recos[reco.recommendation_id] = reco
        return body


STATE: State | None = None


def _tokens_css() -> bytes:
    text = (ROOT / "web/src/styles/tokens.css").read_text()
    # fontsource packages are not installed offline; the token font stacks fall back.
    return re.sub(r'^@import "@fontsource[^\n]*\n', "", text, flags=re.M).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "HospitalOS-DS-local/0.1"

    def log_message(self, *args: object) -> None:  # quiet
        return

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: Any, code: int = 200) -> None:
        self._send(code, json.dumps(value, ensure_ascii=False).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        assert STATE is not None
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in STATIC:
            name, kind = STATIC[url.path]
            return self._send(200, (HERE / name).read_bytes(), kind)
        if url.path == "/tokens.css":
            return self._send(200, _tokens_css(), "text/css; charset=utf-8")
        if url.path == "/app.css":
            return self._send(
                200, (ROOT / "web/src/styles/app.css").read_bytes(), "text/css; charset=utf-8"
            )
        if url.path == "/api/units":
            return self._json(
                {"units": [{"id": k, "name": v} for k, v in UNITS.items()], "events": STATE.events}
            )
        if url.path == "/api/auto":
            unit = q.get("unit", "nominal_auto")
            if unit not in UNITS:
                return self._json({"error": "unknown unit"}, 404)
            with STATE.lock:
                snapshot = STATE.snapshot(unit)
                body = STATE.keep(recommend(snapshot, STATE.settings))
                STATE.docs[snapshot.snapshot_id] = snapshot.model_dump(mode="json")
            return self._json(
                {
                    "doc_id": body["recommendation_id"],
                    "unit": unit,
                    "snapshot_doc_id": snapshot.snapshot_id,
                    "snapshot": STATE.docs[snapshot.snapshot_id],
                    "recommendation": body,
                }
            )
        if url.path.startswith("/api/doc/"):
            doc = STATE.docs.get(url.path.rsplit("/", 1)[-1])
            return self._json(doc) if doc is not None else self._json({"error": "unknown"}, 404)
        return self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        assert STATE is not None
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        url = urlparse(self.path)
        unit = payload.get("unit", "nominal_auto")
        if unit not in UNITS:
            return self._json({"error": "unknown unit"}, 404)
        with STATE.lock:
            if url.path == "/api/simulate":
                try:
                    locks = ScenarioLocks.model_validate(payload["locks"])
                except Exception as error:  # noqa: BLE001 - reported to the user as is
                    return self._json({"error": f"invalid locks: {error}"}, 422)
                body = STATE.keep(simulate(STATE.snapshot(unit), locks, STATE.settings))
                return self._json({"doc_id": body["recommendation_id"], "recommendation": body})
            if url.path == "/api/review":
                reco = STATE.recos.get(payload.get("recommendation_id", ""))
                if reco is None:
                    return self._json({"error": "unknown recommendation"}, 404)
                now = reco.created_at + timedelta(minutes=int(payload.get("minutes_after", 5)))
                result = review(
                    reco,
                    payload["decision"],
                    STATE.snapshot(unit),
                    now,
                    payload["idempotency_key"],
                    STATE.store,
                )
                body = result.model_dump(mode="json")
                STATE.docs[result.review_id] = body
                return self._json({"doc_id": result.review_id, "review": body})
            if url.path == "/api/inject":
                event = next((e for e in STATE.events if e["id"] == payload.get("event")), None)
                if event is None or event["unit"] != unit:
                    return self._json({"error": "unknown demo event"}, 404)
                if event["observation"] not in STATE.injected[unit]:
                    STATE.injected[unit].append(event["observation"])
                return self._json(
                    {
                        "injected": event["id"],
                        "snapshot_fingerprint": STATE.snapshot(unit).fingerprint,
                    }
                )
            if url.path == "/api/reset":
                STATE.injected[unit] = []
                return self._json({"reset": unit})
        return self._json({"error": "not found"}, 404)


def main() -> None:
    global STATE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    STATE = State()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"READY http://127.0.0.1:{httpd.server_address[1]}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
