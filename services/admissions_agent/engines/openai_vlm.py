"""Open-weight vision model engine, behind an OpenAI-compatible endpoint (vLLM, SGLang).

Open computer-use models do not share one documented action format (Holo4's harness is
not public; Qwen-based models differ in coordinate conventions). This engine therefore
defines its own small action set as function-calling tools, and the coordinate
convention is a setting: ``normalized_1000`` (0-1000 on each axis, the Qwen-VL family
convention) or ``pixels`` (screenshot pixels). The calibration test
(``python -m services.admissions_agent calibrate``) measures which one a deployed model
follows; the router refuses an open engine that has not passed it.

Serve the model with tool calling enabled, for example:
    vllm serve Hcompany/Holo4-35B-A3B --enable-auto-tool-choice --tool-call-parser hermes
(the right parser depends on the model's chat template: check its model card).
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.engines.base import (
    SYSTEM_PROMPT,
    BudgetExceeded,
    EngineResult,
    Goal,
    cost_from_tokens,
    parse_final,
)

KEEP_SCREENSHOTS = 2


def _fn(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def tools(convention: str) -> list[dict[str, Any]]:
    unit = (
        "de 0 à 1000 sur chaque axe"
        if convention == "normalized_1000"
        else "en pixels de la capture"
    )
    xy = {"x": {"type": "number"}, "y": {"type": "number"}}
    return [
        _fn(
            "click",
            f"Cliquer à la position (x, y), {unit}.",
            {**xy, "double": {"type": "boolean"}},
            ["x", "y"],
        ),
        _fn(
            "type_text",
            "Saisir du texte là où se trouve le curseur.",
            {"text": {"type": "string"}},
            ["text"],
        ),
        _fn(
            "press_key",
            "Appuyer sur une touche : Enter, Tab, Escape, Backspace, ArrowDown...",
            {"key": {"type": "string"}},
            ["key"],
        ),
        _fn(
            "scroll",
            f"Faire défiler à la position (x, y), {unit}.",
            {**xy, "direction": {"type": "string", "enum": ["up", "down"]}},
            ["x", "y", "direction"],
        ),
        _fn(
            "finish",
            "Terminer la tâche en donnant le résultat demandé (avec la balise <resultat>).",
            {"result": {"type": "string"}},
            ["result"],
        ),
    ]


class OpenWeightsVision:
    def __init__(
        self,
        name: str,
        model: str,
        http: httpx.Client,
        api_key: str | None,
        convention: str,
        input_usd_per_mtok: float = 0.0,
        output_usd_per_mtok: float = 0.0,
        usd_per_hour: float = 0.0,
        max_tokens: int = 1024,
    ) -> None:
        if convention not in ("normalized_1000", "pixels"):
            raise ValueError("convention de coordonnées inconnue")
        self.name = name
        self.model = model
        self.http = http
        self.api_key = api_key
        self.convention = convention
        self.input_price = input_usd_per_mtok
        self.output_price = output_usd_per_mtok
        self.usd_per_hour = usd_per_hour
        self.max_tokens = max_tokens

    def to_pixels(self, session: BrowserSession, x: float, y: float) -> tuple[float, float]:
        if self.convention == "normalized_1000":
            w, h = session.viewport
            return x / 1000.0 * w, y / 1000.0 * h
        return x, y

    def _shot(self, session: BrowserSession, note: str) -> dict[str, Any]:
        png = session.screenshot().png
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": note},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()},
                },
            ],
        }

    def _trim(self, messages: list[dict[str, Any]]) -> None:
        seen = 0
        for message in reversed(messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for i, part in enumerate(content):
                if isinstance(part, dict) and part.get("type") == "image_url":
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        content[i] = {"type": "text", "text": "[capture plus ancienne retirée]"}

    def _act(self, session: BrowserSession, name: str, args: dict[str, Any]) -> str:
        if name == "click":
            x, y = self.to_pixels(session, float(args["x"]), float(args["y"]))
            session.click(x, y, count=2 if args.get("double") else 1)
        elif name == "type_text":
            session.type_text(str(args["text"]))
        elif name == "press_key":
            session.key(str(args["key"]))
        elif name == "scroll":
            x, y = self.to_pixels(session, float(args["x"]), float(args["y"]))
            session.scroll(x, y, 0, 400 if args.get("direction") == "down" else -400)
        else:
            raise ValueError(f"action inconnue : {name}")
        return "OK"

    def run(
        self, session: BrowserSession, goal: Goal, max_steps: int, budget_usd: float
    ) -> EngineResult:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            self._shot(session, goal.instructions + "\nVoici l'écran actuel."),
        ]
        cost = 0.0
        token_cost = 0.0
        trace: list[str] = []
        for step in range(1, max_steps + 1):
            self._trim(messages)
            response = self.http.post(
                "/v1/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools(self.convention),
                    "tool_choice": "required",
                    "max_tokens": self.max_tokens,
                    "temperature": 0,
                },
                timeout=180,
            )
            elapsed_h = (time.monotonic() - started) / 3600
            if response.status_code != 200:
                return EngineResult(
                    "failure",
                    None,
                    cost,
                    step,
                    time.monotonic() - started,
                    f"modèle {response.status_code} : {response.text[:300]}",
                    trace,
                )
            body = response.json()
            usage = body.get("usage") or {}
            token_cost += cost_from_tokens(
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                self.input_price,
                self.output_price,
            )
            # Self-hosted engines cost GPU time; hosted ones cost tokens. Both are counted.
            cost = token_cost + elapsed_h * self.usd_per_hour
            message = body["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
            if not calls:
                ok, data, error = parse_final(message.get("content") or "", goal)
                return EngineResult(
                    "success" if ok else "failure",
                    data,
                    cost,
                    step,
                    time.monotonic() - started,
                    error,
                    trace,
                )
            if cost > budget_usd:
                raise BudgetExceeded(f"{self.name} : budget de la tâche dépassé ({cost:.3f} $)")
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if fn.get("name") == "finish":
                    ok, data, error = parse_final(str(args.get("result", "")), goal)
                    return EngineResult(
                        "success" if ok else "failure",
                        data,
                        cost,
                        step,
                        time.monotonic() - started,
                        error,
                        trace,
                    )
                try:
                    outcome = self._act(session, str(fn.get("name")), args)
                    trace.append(f"{fn.get('name')} {args}")
                except Exception as exc:  # noqa: BLE001 - reported to the model
                    outcome = f"Erreur : {exc}"
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": outcome}
                )
            messages.append(self._shot(session, "Écran après tes actions."))
        return EngineResult(
            "failure",
            None,
            cost,
            max_steps,
            time.monotonic() - started,
            "nombre maximal d'étapes atteint",
            trace,
        )
