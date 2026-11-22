#!/usr/bin/env python3
"""One-shot hook client for the Clawd-Mochi extended bridge.

Drop this in any agent's hook config, e.g. Claude Code / Codex / Cursor / Qoder /
Gemini CLI / Copilot / Trae / WorkBuddy, or any script of your own.

    python mochi_hook.py coding
    python mochi_hook.py coding --text "Bash: npm test"
    python mochi_hook.py coding --stdin tool_name     # read hook JSON from stdin
    python mochi_hook.py waiting --text "needs permission"
    python mochi_hook.py done
    python mochi_hook.py idle --bg 101820 --speed 1
    python mochi_hook.py coding --progress 0.42        # needs --canvas bridge

Design notes
------------
* Never blocks the agent: total budget is ~1.2 s, every failure is swallowed,
  and the process always exits 0.
* If the extended bridge (18894) is not running it degrades to the stock bridge
  (18892) for the 7 states that one understands.
* Exit code is always 0 on purpose: several agents abort the tool call when a
  PreToolUse hook exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request

BRIDGE = "http://127.0.0.1:{port}/event"
STOCK = "http://127.0.0.1:{port}/event?s={event}"
STOCK_EVENTS = {"idle", "thinking", "coding", "waiting", "done", "error", "sleep"}
ALIAS = {"busy": "coding", "working": "coding", "ask": "waiting", "confirm": "waiting",
         "fail": "error", "rest": "sleep", "wake": "idle", "plan": "planning",
         "subagent": "delegating", "compact": "compacting"}


def get_stdin_json(limit: int = 65536):
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read(limit)
        return json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        return {}


def pick(data: dict, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
    if isinstance(cur, (dict, list)):
        return json.dumps(cur, ensure_ascii=False)
    return None if cur is None else str(cur)


def call(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:  # noqa: BLE001
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("event")
    ap.add_argument("-t", "--text", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--bg", default="")
    ap.add_argument("--speed", type=int, default=None)
    ap.add_argument("--bl", type=int, default=None)
    ap.add_argument("--progress", type=float, default=None)
    ap.add_argument("--stdin", default="", help="dot-path of a field in the hook's stdin JSON to use as text")
    ap.add_argument("--port", type=int, default=18894)
    ap.add_argument("--stock-port", type=int, default=18892)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    event = args.event.strip().lower()
    event = ALIAS.get(event, event)

    text = args.text
    if args.stdin:
        data = get_stdin_json()
        value = pick(data, args.stdin)
        if value:
            text = value if not text else f"{text} {value}"

    params = {"e": event}
    if text:
        params["t"] = text
    if args.label:
        params["label"] = args.label
    if args.bg:
        params["bg"] = args.bg
    if args.speed is not None:
        params["sp"] = str(args.speed)
    if args.bl is not None:
        params["bl"] = str(args.bl)
    if args.progress is not None:
        params["p"] = f"{args.progress:g}"

    url = BRIDGE.format(port=args.port) + "?" + urllib.parse.urlencode(params)
    ok = call(url, 0.9)
    if not ok and event in STOCK_EVENTS:
        ok = call(STOCK.format(port=args.stock_port, event=urllib.parse.quote(event)), 1.0)
    if not args.quiet and not ok:
        print(f"mochi_hook: bridge and stock both unreachable ({event})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the agent
        sys.exit(0)
