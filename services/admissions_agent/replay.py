"""Agent player, worker side: record each step and send it to HospitalOS, best effort.

Each step is a plain-French label (never a value read on screen: labels are static text
from the code or the playbook, never templated), the gesture (pointer, element box), the
outcome and duration, and a JPEG frame **masked on this machine before capture** with
Playwright's native masking (docs/agent/PLAYER_SPEC.md):

* the playbook's ``privacy`` section declares the zones to mask, per screen;
* password inputs and every field the agent filled with a credential are always masked;
* fail closed: a playbook without ``privacy`` produces no frame at all (the transcript
  stays); a zone declared for the current screen and not found withholds the frame, and
  the step says so.

Uploads never block nor fail the task: a background thread posts the steps with a short
timeout from a bounded queue; when HospitalOS is slow, frames are dropped first (steps
are kept); nothing is retried, and the thread stops for good once the lease is lost.
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("admissions_agent.replay")

MASK_COLOR = "#4B5563"  # flat slate: the player draws its own hatching and caption on top
JPEG_QUALITY = 60
MAX_WIDTH = 1280
MAX_FRAME_BYTES = 512 * 1024
REASONS = ("identite", "secret", "autre")
ALWAYS_MASKED = "input[type=password]"
WITHHELD_MISSING = "capture retenue : zone à protéger introuvable"
WITHHELD_WIDE = "capture retenue : écran plus large que 1280 px"
WITHHELD_HEAVY = "capture retenue : image trop lourde"
WITHHELD_MOVED = "capture retenue : la page a changé pendant la capture"
_BOXES_JS = (
    "els => els.map(e => { const r = e.getBoundingClientRect();"
    " return [r.x, r.y, r.width, r.height]; })"
)


class PrivacyError(ValueError):
    """The playbook's privacy section is malformed."""


@dataclass(frozen=True)
class MaskRule:
    selector: str
    reason: str
    screens: tuple[str, ...] = ()  # path patterns (fnmatch); empty: wherever it appears
    optional: bool = False

    def applies(self, path: str) -> bool:
        return not self.screens or any(fnmatch.fnmatchcase(path, p) for p in self.screens)

    def required(self, path: str) -> bool:
        return bool(self.screens) and not self.optional and self.applies(path)


@dataclass(frozen=True)
class Privacy:
    """``rules`` is None when the playbook declares no privacy section: no frames."""

    rules: tuple[MaskRule, ...] | None = None

    @property
    def enabled(self) -> bool:
        return self.rules is not None

    @classmethod
    def from_spec(cls, spec: Any) -> Privacy:
        """``privacy: {mask: [{selector, reason, screen?, optional?}]}``; ``screen`` is a
        path pattern or a list of them (``/dossiers/*``)."""
        if spec is None:
            return cls(None)
        if not isinstance(spec, dict) or not isinstance(spec.get("mask", []), list):
            raise PrivacyError("section privacy invalide : privacy.mask doit être une liste")
        rules = []
        for item in spec.get("mask", []):
            if not isinstance(item, dict) or not isinstance(item.get("selector"), str):
                raise PrivacyError("privacy.mask : chaque zone a un selector")
            reason = item.get("reason", "identite")
            if reason not in REASONS:
                raise PrivacyError(f"privacy.mask : motif inconnu ({', '.join(REASONS)})")
            screens = item.get("screen", ())
            screens = (screens,) if isinstance(screens, str) else tuple(screens)
            if not all(isinstance(s, str) and s.startswith("/") for s in screens):
                raise PrivacyError("privacy.mask : screen est un chemin commençant par /")
            unknown = set(item) - {"selector", "reason", "screen", "optional"}
            if unknown:
                raise PrivacyError(f"privacy.mask : clé inconnue {sorted(unknown)[0]}")
            rules.append(MaskRule(item["selector"], reason, screens, bool(item.get("optional"))))
        return cls(tuple(rules))


@dataclass
class Step:
    """What a running step may still change before it is sent (verdict known at the end)."""

    label: str
    transmitted: dict[str, Any] | None = None
    outcome: str = "ok"


@dataclass
class Recorder:
    """Disabled (records nothing) without a sink: calibration, tests without API."""

    sink: StepUploader | None = None
    privacy: Privacy = field(default_factory=Privacy)
    engine: str = "playbook"
    seq_base: int = 0
    page: Any = None
    viewport: tuple[int, int] = (1280, 800)
    secret_selectors: set[str] = field(default_factory=set)
    _seq: int = 0

    def attach(self, session: Any) -> None:
        self.page = getattr(session, "page", None)
        self.viewport = tuple(getattr(session, "viewport", self.viewport))

    @contextlib.contextmanager
    def step(
        self,
        kind: str,
        label: str,
        *,
        target: str | None = None,
        selector: str | None = None,
        pointer: Any = None,
        capture: str | None = "after",
        engine: str | None = None,
    ) -> Iterator[Step]:
        """Time the action inside the block and send it as one step (``fail`` if it
        raises; the exception goes on). ``capture``: "before" (clicks: the frame shows
        what is clicked), "after", or None (the player keeps the previous frame)."""
        current = Step(label)
        if self.sink is None:
            yield current
            return
        started = time.monotonic()
        at = datetime.now(UTC)
        box = self._box(selector) if selector else None
        point = _point(pointer) if pointer is not None else None
        if box and point is None and capture == "before":  # a click: the element's centre
            point = {"x": box["x"] + box["w"] / 2, "y": box["y"] + box["h"] / 2}
        shot = self._capture() if capture == "before" else None
        try:
            yield current
        except BaseException:
            current.outcome = "fail"
            raise
        finally:
            if capture == "after":
                shot = self._capture()
            self._send(kind, current, at, started, target, point, box, shot, engine)

    def info(
        self,
        label: str,
        *,
        kind: str = "info",
        outcome: str = "info",
        transmitted: dict[str, Any] | None = None,
    ) -> None:
        if self.sink is not None:
            now = time.monotonic()
            step = Step(label, transmitted, outcome)
            self._send(kind, step, datetime.now(UTC), now, None, None, None, None, None)

    def close(self, timeout: float = 5.0) -> None:
        if self.sink is not None:
            self.sink.close(timeout)

    # --- internals -----------------------------------------------------------------

    def _send(
        self,
        kind: str,
        step: Step,
        at: datetime,
        started: float,
        target: str | None,
        pointer: dict[str, float] | None,
        box: dict[str, float] | None,
        shot: tuple[bytes | None, list[dict[str, Any]], str | None] | None,
        engine: str | None,
    ) -> None:
        assert self.sink is not None
        frame, masks, note = shot or (None, [], None)
        label = f"{step.label} ({note})" if note else step.label
        self._seq += 1
        meta = {
            "seq": self.seq_base + self._seq,
            "at": at.isoformat(),
            "engine": engine or self.engine,
            "kind": kind,
            "label": label[:300],
            "target": target[:200] if target else None,
            "pointer": pointer,
            "box": box,
            "outcome": step.outcome,
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            "viewport": {"w": int(self.viewport[0]), "h": int(self.viewport[1])},
            "masks": masks[:200],
            "transmitted": step.transmitted,
        }
        self.sink.submit(meta, frame)

    def _box(self, selector: str) -> dict[str, float] | None:
        try:
            found = self.page.locator(selector).first.bounding_box(timeout=1000)
            return _rect(found["x"], found["y"], found["width"], found["height"]) if found else None
        except Exception:  # noqa: BLE001 - a gesture without box is still a step
            return None

    def _capture(self) -> tuple[bytes | None, list[dict[str, Any]], str | None]:
        """(frame, masked rectangles, why the frame was withheld). Never raises."""
        if not self.privacy.enabled or self.page is None:
            return None, [], None
        if self.viewport[0] > MAX_WIDTH:
            return None, [], WITHHELD_WIDE
        try:
            return self._masked_screenshot()
        except Exception:  # noqa: BLE001 - recording must never break the task
            log.debug("capture impossible", exc_info=True)
            return None, [], None

    def _masked_screenshot(self) -> tuple[bytes | None, list[dict[str, Any]], str | None]:
        page = self.page
        url = page.url
        path = urlparse(url).path or "/"
        zones: list[tuple[Any, str]] = [(page.locator(ALWAYS_MASKED), "secret")]
        zones += [(page.locator(s), "secret") for s in sorted(self.secret_selectors)]
        for rule in self.privacy.rules or ():
            if not rule.applies(path):
                continue
            locator = page.locator(rule.selector)
            if rule.required(path) and locator.count() == 0:
                return None, [], WITHHELD_MISSING
            zones.append((locator, rule.reason))
        masks = [
            {**rect, "reason": reason}
            for locator, reason in zones
            for x, y, w, h in locator.evaluate_all(_BOXES_JS)
            if w > 0 and h > 0 and (rect := _rect(x, y, w, h))
        ]
        frame: bytes = page.screenshot(
            type="jpeg",
            quality=JPEG_QUALITY,
            scale="css",
            mask=[locator for locator, _ in zones],
            mask_color=MASK_COLOR,
            animations="disabled",
            caret="hide",
            timeout=3000,
        )
        if page.url != url:  # navigated between the zone check and the capture
            return None, [], WITHHELD_MOVED
        if len(frame) > MAX_FRAME_BYTES:
            return None, masks, WITHHELD_HEAVY
        return frame, masks, None


def _rect(x: float, y: float, w: float, h: float) -> dict[str, float]:
    def clamp(v: float, low: float) -> float:
        return round(min(max(float(v), low), 20000.0), 1)

    return {"x": clamp(x, -20000), "y": clamp(y, -20000), "w": clamp(w, 0), "h": clamp(h, 0)}


def _point(pointer: Any) -> dict[str, float] | None:
    try:  # a model's coordinates are untrusted: never let them break the step
        x, y = (min(max(float(v), -20000.0), 20000.0) for v in pointer)
    except (TypeError, ValueError):
        return None
    return {"x": round(x, 1), "y": round(y, 1)}


# --- model engines ----------------------------------------------------------------------

_DIRECTIONS = {"up": "le haut", "down": "le bas", "left": "la gauche", "right": "la droite"}
MODEL_LABELS = {
    "left_click": "Clique à l'endroit choisi par le modèle",
    "double_click": "Double-clique à l'endroit choisi par le modèle",
    "triple_click": "Triple-clique à l'endroit choisi par le modèle",
    "right_click": "Clic droit à l'endroit choisi par le modèle",
    "middle_click": "Clic du milieu à l'endroit choisi par le modèle",
    "mouse_move": "Déplace le pointeur",
    "cursor_position": "Repère la position du pointeur",
    "screenshot": "Regarde l'écran",
    "wait": "Attend que la page se mette à jour",
}
CLICKS = {"left_click", "double_click", "triple_click", "right_click", "middle_click"}


def model_label(
    action: str, *, chars: int = 0, key: str | None = None, direction: Any = None
) -> str:
    """A model action in plain French. Never the typed text (only its length), a key
    name only from the allowlist (``key`` is passed by the engine once checked)."""
    if action == "type":
        return f"Saisit un texte ({chars} caractère{'s' if chars > 1 else ''})"
    if action == "key":
        return f"Appuie sur la touche {key}" if key else "Appuie sur une touche"
    if action == "scroll":
        return f"Fait défiler vers {_DIRECTIONS.get(str(direction), 'le bas')}"
    return MODEL_LABELS.get(action, "Action du modèle refusée")


# --- uploads ---------------------------------------------------------------------------


class StepRefused(RuntimeError):
    """HospitalOS refused the step (lease lost, task finished): stop sending."""


class StepUploader:
    """Bounded queue drained by one daemon thread. ``post(meta, frame, timeout)`` sends
    one step; it raises ``StepRefused`` when the task no longer accepts steps."""

    def __init__(
        self,
        post: Callable[[dict[str, Any], bytes | None, float], None],
        max_steps: int = 300,
        max_frames: int = 6,
        timeout: float = 3.0,
    ) -> None:
        self.post = post
        self.timeout = timeout
        self.max_frames = max_frames
        self.queue: queue.Queue[tuple[dict[str, Any], bytes | None]] = queue.Queue(max_steps)
        self.queued_frames = 0
        self.dropped_frames = 0
        self.dropped_steps = 0
        self.stopped = False
        self.closing = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="replay-upload", daemon=True)
        self.thread.start()

    def submit(self, meta: dict[str, Any], frame: bytes | None) -> None:
        if self.stopped or self.closing:
            return
        with self.lock:
            if frame is not None and self.queued_frames >= self.max_frames:
                frame, self.dropped_frames = None, self.dropped_frames + 1
            if frame is not None:
                self.queued_frames += 1
        try:
            self.queue.put_nowait((meta, frame))
        except queue.Full:
            with self.lock:
                self.dropped_steps += 1
                self.queued_frames -= frame is not None

    def _run(self) -> None:
        failures = 0
        while True:
            try:
                meta, frame = self.queue.get(timeout=0.1)
            except queue.Empty:
                if self.closing:
                    return
                continue
            if frame is not None:
                with self.lock:
                    self.queued_frames -= 1
            if self.stopped:
                continue
            try:
                self.post(meta, frame, self.timeout)
                failures = 0
            except StepRefused:
                self.stopped = True
            except Exception:  # noqa: BLE001 - never retried: the step is dropped
                failures += 1
                self.dropped_steps += 1
                if failures >= 3:
                    self.stopped = True

    def close(self, timeout: float = 5.0) -> None:
        """Wait at most ``timeout`` seconds for the queue to drain; drop the rest."""
        self.closing = True
        self.thread.join(timeout)
        if self.thread.is_alive():
            self.stopped = True
        if self.dropped_frames or self.dropped_steps:
            log.info(
                "player : %s image(s) et %s étape(s) non envoyées",
                self.dropped_frames,
                self.dropped_steps,
            )
