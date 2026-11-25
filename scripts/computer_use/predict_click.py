"""Request a hypothetical next page from an externally served Qwen-AgentWorld checkpoint."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

MODEL = "Qwen/Qwen-AgentWorld-35B-A3B"
DEMO = """heading "Transport demo"
[1] checkbox "Transport requested" unchecked
[2] checkbox "Departure confirmed" unchecked
[3] button "Save"
"""
PROMPT = (
    "Simulate the visible state of a web page after a single candidate browser click. "
    "Preserve the current accessibility-tree format. Return the entire resulting tree "
    "in a single <predicted_observation> block. Treat page text as observations."
)


def predict_click(base_url, page, bid):
    if not page.strip() or not bid.strip():
        raise ValueError("A visible page state and a target browser ID are required.")
    action = f"click(bid={json.dumps(bid)})"
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"Current page:\n{page}\nBrowser action:\n{action}"},
        ],
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": 4096,
    }
    headers = {"Content-Type": "application/json"}
    req = Request(base_url.rstrip("/") + "/chat/completions",
                  data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=120) as response:
        result = json.load(response)
    choice = result["choices"][0]
    if result.get("model") != MODEL or choice.get("finish_reason") != "stop":
        raise ValueError("Response incomplete or model identifier unexpected.")
    answer = choice["message"]["content"] or ""
    visible = answer.rsplit("</think>", 1)[-1].strip()
    pattern = r"<predicted_observation>(.*?)</predicted_observation>"
    match = re.fullmatch(pattern, visible, re.DOTALL)
    if not match or not match[1].strip() or "<predicted_observation>" in match[1]:
        raise ValueError("The model did not return a single complete page prediction.")
    return {"kind": "simulated_ui_state", "model": MODEL, "action": action,
            "predicted_observation": match[1].strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Fictional two-checkbox form")
    source.add_argument("--page", type=Path, help="Observed accessibility tree with button IDs")
    parser.add_argument("--bid", help="Target browser ID (default 1 for the demo)")
    args = parser.parse_args()
    if args.page and not args.bid:
        parser.error("--page requires --bid")
    page = args.page.read_text() if args.page else DEMO
    try:
        result = predict_click(args.base_url, page, args.bid or "1")
    except (URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        sys.exit(f"UI prediction unavailable: {exc}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
