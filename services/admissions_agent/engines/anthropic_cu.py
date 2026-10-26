"""Claude computer use engine (Anthropic Messages API, ``computer_toolset_20260801``).

Contract followed (platform.claude.com, computer use tool reference, Oct. 2026):
- tool declared as ``{"type": "computer_toolset_20260801"}``, no beta header;
- each ``tool_use`` block names a member (``left_click``, ``screenshot``...) and carries
  ``"toolset_name": "computer"``; every ``tool_result`` echoes it;
- coordinates are in the pixel space of the screenshots we return (1280x800 here, within
  the image limits of the supported models, so no rescaling is needed);
- after a failed action, the remaining actions of the same turn are answered as not
  executed, since the model planned them assuming success.

Called over plain HTTP so the request is fully visible and testable.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from services.admissions_agent.api_client import TaskInterrupted
from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.engines.base import (
    SYSTEM_PROMPT,
    BudgetExceeded,
    EngineResult,
    Goal,
    cost_from_tokens,
    parse_final,
)

TOOLSET = {"type": "computer_toolset_20260801", "configs": {"zoom": {"enabled": False}}}
API_VERSION = "2023-06-01"
NOT_EXECUTED = "Non exécuté : une action précédente de ce tour a échoué."
REFUSED_MEMBERS = {"left_click_drag", "left_mouse_down", "left_mouse_up", "hold_key", "zoom"}
KEEP_SCREENSHOTS = 3


class AnthropicComputerUse:
    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        http: httpx.Client,
        input_usd_per_mtok: float,
        output_usd_per_mtok: float,
        max_tokens: int = 2048,
    ) -> None:
        self.name = name
        self.model = model
        self.api_key = api_key
        self.http = http
        self.input_price = input_usd_per_mtok
        self.output_price = output_usd_per_mtok
        self.max_tokens = max_tokens
        self.incurred_cost = 0.0
        self.cursor = (0.0, 0.0)

    def _screenshot_block(self, session: BrowserSession) -> dict[str, Any]:
        shot = session.screenshot()
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(shot.png).decode(),
            },
        }

    def _act(self, session: BrowserSession, member: str, args: dict[str, Any]) -> Any:
        if member in REFUSED_MEMBERS:
            raise ValueError(f"action {member} non autorisée dans cet agent")
        if member == "screenshot":
            return [self._screenshot_block(session)]
        if member in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
            if args.get("text"):
                raise ValueError("clic avec touches de modification non autorisé")
            x, y = args.get("coordinate") or self.cursor
            button = {"right_click": "right", "middle_click": "middle"}.get(member, "left")
            count = {"double_click": 2, "triple_click": 3}.get(member, 1)
            session.click(float(x), float(y), button=button, count=count)
            self.cursor = (float(x), float(y))
            return "OK"
        if member == "mouse_move":
            x, y = args["coordinate"]
            session.move(float(x), float(y))
            self.cursor = (float(x), float(y))
            return "OK"
        if member == "cursor_position":
            return f"[{int(self.cursor[0])}, {int(self.cursor[1])}]"
        if member == "type":
            session.type_text(str(args["text"]))
            return "OK"
        if member == "key":
            session.key(str(args["text"]), int(args.get("repeat", 1)))
            return "OK"
        if member == "scroll":
            x, y = args.get("coordinate") or self.cursor
            amount = int(args.get("scroll_amount", 3)) * 100
            dx, dy = {
                "up": (0, -amount),
                "down": (0, amount),
                "left": (-amount, 0),
                "right": (amount, 0),
            }[str(args.get("scroll_direction", "down"))]
            session.scroll(float(x), float(y), dx, dy)
            return "OK"
        if member == "wait":
            time.sleep(min(float(args.get("duration", 1)), 10.0))
            return "OK"
        raise ValueError(f"action inconnue : {member}")

    def _trim(self, messages: list[dict[str, Any]]) -> None:
        """Keep only the last screenshots in the history to bound cost."""
        seen = 0
        for message in reversed(messages):
            if not isinstance(message.get("content"), list):
                continue
            for block in message["content"]:
                parts = block.get("content") if block.get("type") == "tool_result" else [block]
                if not isinstance(parts, list):
                    continue
                for i, part in enumerate(parts):
                    if isinstance(part, dict) and part.get("type") == "image":
                        seen += 1
                        if seen > KEEP_SCREENSHOTS:
                            parts[i] = {"type": "text", "text": "[capture plus ancienne retirée]"}

    def close(self) -> None:
        self.http.close()

    def run(
        self, session: BrowserSession, goal: Goal, max_steps: int, budget_usd: float
    ) -> EngineResult:
        self.incurred_cost = 0.0
        started = time.monotonic()
        try:
            return self._run(session, goal, max_steps, budget_usd)
        except (TaskInterrupted, BudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - preserve already billed calls on failure
            return EngineResult(
                "failure",
                cost_usd=self.incurred_cost,
                duration_s=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _run(
        self, session: BrowserSession, goal: Goal, max_steps: int, budget_usd: float
    ) -> EngineResult:
        started = time.monotonic()
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": goal.instructions},
                    self._screenshot_block(session),
                ],
            }
        ]
        cost = 0.0
        trace: list[str] = []
        for step in range(1, max_steps + 1):
            session.checkpoint()
            self._trim(messages)
            response = self.http.post(
                "/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION},
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": SYSTEM_PROMPT,
                    "tools": [TOOLSET],
                    "messages": messages,
                },
                timeout=120,
            )
            if response.status_code != 200:
                return EngineResult(
                    "failure",
                    None,
                    cost,
                    step,
                    time.monotonic() - started,
                    f"API Anthropic {response.status_code} : {response.text[:300]}",
                    trace,
                )
            body = response.json()
            usage = body.get("usage", {})
            # Cache tokens are billed at full input price here: an overestimate, safe for budgets.
            cost += cost_from_tokens(
                int(usage.get("input_tokens", 0))
                + int(usage.get("cache_read_input_tokens", 0) or 0)
                + int(usage.get("cache_creation_input_tokens", 0) or 0),
                int(usage.get("output_tokens", 0)),
                self.input_price,
                self.output_price,
            )
            self.incurred_cost = cost
            if cost > budget_usd:
                raise BudgetExceeded(
                    f"{self.name} : budget de la tâche dépassé ({cost:.3f} $)", cost
                )
            content = body.get("content", [])
            messages.append({"role": "assistant", "content": content})
            calls = [b for b in content if b.get("type") == "tool_use"]
            if not calls:
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                ok, data, error = parse_final(text, goal)
                return EngineResult(
                    "success" if ok else "failure",
                    data,
                    cost,
                    step,
                    time.monotonic() - started,
                    error,
                    trace,
                )
            results: list[dict[str, Any]] = []
            failed = False
            for call in calls:
                result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "toolset_name": "computer",
                }
                if call.get("toolset_name", "computer") != "computer":
                    result["content"] = "Outil inconnu"
                    result["is_error"] = True
                elif failed:
                    result["content"] = NOT_EXECUTED
                    result["is_error"] = True
                else:
                    try:
                        result["content"] = self._act(
                            session, call["name"], call.get("input") or {}
                        )
                        trace.append(f"{call['name']} {call.get('input') or ''}")
                    except TaskInterrupted:
                        raise
                    except Exception as exc:  # noqa: BLE001 - reported to the model, not raised
                        result["content"] = f"Erreur : {exc}"
                        result["is_error"] = True
                        failed = True
                results.append(result)
            messages.append({"role": "user", "content": results})
        return EngineResult(
            "failure",
            None,
            cost,
            max_steps,
            time.monotonic() - started,
            "nombre maximal d'étapes atteint",
            trace,
        )
