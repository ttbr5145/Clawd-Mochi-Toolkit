#!/usr/bin/env python3
"""Clawd-Mochi extended hook bridge (localhost:18894).

Why this exists
---------------
The stock control center (Clawd-Mochi.exe) only accepts 7 state names on
http://127.0.0.1:18892/event?s=<state> and forwards them to the pet.  The pet
firmware itself understands 13 event names and exposes a much richer HTTP API
(terminal text, canvas drawing, background colour, animation speed, backlight).
This bridge sits in front of that API so *hooks* can drive the richer features
while still keeping the stock 6-state animation working.

Routing
-------
  hook -> GET http://127.0.0.1:18894/event?e=<event>&t=<text>&bg=RRGGBB&sp=1-3&bl=0|1&p=0..1
          or POST /json  {"event": "...", "text": "...", ...}

State names accepted: idle thinking coding reading running delegating compacting
waiting notify done error sleep (+ aliases busy/working/ask/fail/rest/wake).

Two layers:
  * state layer  -> forwarded to 18892 (stock animation) and to the device for
                    the 7 states the stock bridge also knows.
  * enrichment   -> spoken straight to the pet's HTTP API:
        bg=RRGGBB   background colour          (/redraw?bg=)
        sp=1|2|3    animation speed            (/speed?v=)
        bl=0|1      backlight                  (/backlight?on=)
        t=TEXT      terminal line (opt-in, --terminal)   (/cmd?k=d, /char)
        p=0..1      progress bar  (opt-in, --canvas)     (/canvas, /draw/stroke)

Opt-in flags exist because terminal view and canvas view take over the screen
(the pet's eyes stop animating while they are open).

Usage:
    python mochi_bridge.py                      # 18894, bg/speed/backlight only
    python mochi_bridge.py --terminal            # also allow terminal text
    python mochi_bridge.py --canvas              # also allow progress canvas
    python mochi_bridge.py --host 192.168.1.20   # direct device address
"""
from __future__ import annotations

import argparse
import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

THIRTEEN = (
    "coding", "reading", "running", "delegating", "compacting",
    "idle", "sleep", "thinking", "planning", "waiting", "notify", "done", "error",
)
# only these 7 are understood by the stock bridge on 18892
STOCK = {"idle", "thinking", "coding", "waiting", "done", "error", "sleep"}
ALIAS = {
    "busy": "coding", "working": "coding", "tool": "coding",
    "ask": "waiting", "confirm": "waiting", "approval": "waiting",
    "fail": "error", "failed": "error", "alert": "error",
    "rest": "sleep", "wake": "idle", "start": "thinking",
    "subagent": "delegating", "compact": "compacting", "plan": "planning",
}

# device view ids reported by /state
VIEW_NORMAL, VIEW_SQUISH, VIEW_TERM, VIEW_CANVAS = 0, 1, 2, 3


class Device:
    """Thin, thread-safe client for the pet's own HTTP API."""

    def __init__(self, host: str, timeout: float = 2.5):
        self.base = host if host.startswith("http") else "http://" + host
        self.timeout = timeout
        self._lock = threading.Lock()
        self.connected = False
        self.view = VIEW_NORMAL
        self.term = False
        self.canvas = False

    def _get(self, path: str, timeout: float | None = None):
        url = self.base + path
        try:
            with urllib.request.urlopen(url, timeout=timeout or self.timeout) as r:
                body = r.read(256).decode("utf-8", "replace")
                self.connected = True
                return r.status, body
        except Exception as exc:  # noqa: BLE001
            self.connected = False
            return 0, repr(exc)

    def state(self) -> dict:
        st, body = self._get("/state")
        if st != 200:
            return {}
        try:
            j = json.loads(body)
        except Exception:  # noqa: BLE001
            return {}
        self.view = j.get("view", self.view)
        self.term = bool(j.get("term"))
        return j

    def cmd(self, k: str):
        return self._get("/cmd?k=" + k)

    def char(self, ch: str):
        return self._get("/char?c=" + urllib.parse.quote(ch, safe=""))

    def type_line(self, text: str, speed: int = 3):
        for ch in text:
            self.char("\n" if ch == "\n" else ch)
            time.sleep(0.012 if speed >= 3 else 0.03)

    def bg(self, hex_color: str):
        return self._get("/redraw?bg=" + urllib.parse.quote(hex_color))

    def anim_speed(self, v: int):
        return self._get(f"/speed?v={int(v)}")

    def backlight(self, on: int):
        return self._get(f"/backlight?on={1 if on else 0}")

    def canvas_on(self, on: bool):
        self.canvas = on
        return self._get("/canvas?on=" + ("1" if on else "0"), timeout=6.0)

    def draw_clear(self, hex_color: str):
        return self._get("/draw/clear?bg=" + urllib.parse.quote(hex_color))

    def stroke(self, pts, pen: str):
        payload = ";".join(f"{int(x)},{int(y)}" for x, y in pts)
        return self._get("/draw/stroke?pen=" + pen + "&pts=" + urllib.parse.quote(payload))

    def progress(self, value: float, pen: str = "00FF66"):
        value = max(0.0, min(1.0, float(value)))
        self.draw_clear("000000")
        top, left, width = 150, 8, 224
        self.stroke([(left, top), (left + width - 1, top)], "303030")
        end = left + int((width - 1) * value)
        if end > left:
            self.stroke([(left, top), (end, top)], pen)
            self.stroke([(left, top - 2), (left, top + 2)], pen)
            self.stroke([(end, top - 2), (end, top + 2)], pen)
        return end


class Bridge:
    def __init__(self, device: Device, stock_port: int, terminal: bool, canvas: bool,
                 use_stock: bool = True):
        self.dev = device
        self.stock_port = stock_port
        self.terminal = terminal
        self.canvas = canvas
        self.use_stock = use_stock
        self.q: queue.Queue = queue.Queue(maxsize=512)
        self.last_event = ""
        self.last_event_ts = 0.0
        self.last_text = ""
        self.term_open = False
        self.canvas_open = False
        self.count = 0
        self.errors = 0
        self._timer: threading.Timer | None = None
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # -- public API ---------------------------------------------------
    def submit(self, event: str, text: str = "", bg: str = "", sp=None, bl=None, p=None, label: str = ""):
        ev = (event or "idle").strip().lower()
        ev = ALIAS.get(ev, ev)
        if ev not in THIRTEEN:
            raise ValueError(f"unknown event: {event!r} (allowed: {', '.join(THIRTEEN)})")
        self.q.put({"event": ev, "text": text, "bg": bg, "sp": sp, "bl": bl, "p": p, "label": label})
        return ev

    def forward_stock(self, event: str) -> int:
        """Route a state to the pet.

        The stock control center understands only 7 names (18892); the pet
        itself accepts all 13, so wider names go straight to the device.
        """
        if event in STOCK and self.use_stock:
            url = f"http://127.0.0.1:{self.stock_port}/event?s={urllib.parse.quote(event)}"
            try:
                with urllib.request.urlopen(url, timeout=1.5) as r:
                    return r.status
            except Exception:  # noqa: BLE001
                pass  # stock bridge down -> talk to the pet directly
        try:
            with urllib.request.urlopen(
                    self.dev.base + "/event?s=" + urllib.parse.quote(event), timeout=1.5) as r:
                return r.status
        except Exception:  # noqa: BLE001
            self.errors += 1
            return 0

    def progress(self, value: float):
        self.q.put({"event": "", "progress": value})

    def say(self, text: str, label: str = ""):
        self.q.put({"event": "", "text": text, "label": label})

    def status(self) -> dict:
        return {
            "ok": True,
            "device": self.dev.base,
            "device_connected": self.dev.connected,
            "view": self.dev.view,
            "term_open": self.term_open,
            "canvas_open": self.canvas_open,
            "terminal_enabled": self.terminal,
            "canvas_enabled": self.canvas,
            "stock_bridge": self.use_stock,
            "last_event": self.last_event,
            "events": self.count,
            "errors": self.errors,
            "queue": self.q.qsize(),
        }

    # -- worker -------------------------------------------------------
    def _run(self):
        while True:
            job = self.q.get()
            try:
                self._handle(job)
            except Exception:  # noqa: BLE001
                self.errors += 1
            finally:
                self.q.task_done()

    def _handle(self, job: dict):
        # pure progress update
        if "progress" in job:
            self._do_progress(job["progress"])
            return
        event = job.get("event") or ""

        if job.get("bg"):
            self.dev.bg(job["bg"])
        if job.get("sp") is not None:
            try:
                self.dev.anim_speed(int(job["sp"]))
            except Exception:  # noqa: BLE001
                pass
        if job.get("bl") is not None:
            try:
                self.dev.backlight(int(job["bl"]))
            except Exception:  # noqa: BLE001
                pass
        if "p" in job and job.get("p") is not None and self.canvas:
            self._do_progress(job["p"])

        text = (job.get("text") or "").strip()
        if event:
            self.count += 1
            self.forward_stock(event)
            now = time.time()
            changed = event != self.last_event
            self.last_event, self.last_event_ts = event, now
            if self.terminal and text and (changed or text != self.last_text):
                self._speak(text, job.get("label", ""))
            self.last_text = text
            # leave the takeover views when the agent goes quiet
            if event in ("idle", "sleep"):
                self._release_views()
            elif event == "done":
                self._release_later(6.0)

    def _speak(self, text: str, label: str = ""):
        # the pet can only show one takeover view at a time
        if self.canvas_open:
            self.dev.canvas_on(False)
            self.canvas_open = False
        st = self.dev.state()
        if not st.get("term"):
            self.dev.cmd("d")
            time.sleep(0.3)
        self.term_open = True
        line = (f"{label}: {text}" if label else text)[:120]
        self.dev.type_line(line + "\n")

    def _release_later(self, delay: float):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(delay, self._release_views)
        self._timer.daemon = True
        self._timer.start()

    def _release_views(self):
        if self.term_open:
            self.dev.cmd("q")
            self.term_open = False
        if self.canvas_open:
            self.dev.canvas_on(False)
            self.canvas_open = False

    def _do_progress(self, value):
        if not self.canvas:
            return
        if not self.canvas_open:
            self.dev.canvas_on(True)
            time.sleep(0.3)
            self.canvas_open = True
        self.dev.progress(float(value))


class Handler(BaseHTTPRequestHandler):
    bridge: Bridge = None  # set by main()
    server_version = "mochi-bridge/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        one = lambda k, d="": (qs.get(k, [d])[0] or d)  # noqa: E731
        try:
            if parsed.path in ("/event", "/event/", "/e"):
                ev = one("e") or one("s") or one("event")
                sp = one("sp") or one("speed")
                bl = one("bl")
                p = one("p") or one("progress")
                ev = self.bridge.submit(
                    ev or "idle",
                    text=one("t") or one("text"),
                    bg=one("bg"),
                    sp=int(sp) if sp else None,
                    bl=int(bl) if bl else None,
                    p=float(p) if p else None,
                    label=one("label"),
                )
                self._send(200, {"ok": True, "event": ev})
                return
            if parsed.path == "/say":
                text = one("t") or one("text")
                self.bridge.say(text, one("label"))
                self._send(200, {"ok": True})
                return
            if parsed.path == "/progress":
                self.bridge.progress(float(one("p") or one("progress") or 0))
                self._send(200, {"ok": True})
                return
            if parsed.path in ("/status", "/state"):
                self._send(200, self.bridge.status())
                return
            if parsed.path == "/ping":
                self._send(200, {"ok": True, "pong": True})
                return
            self._send(404, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": repr(exc)})

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/json", "/event"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(min(n, 65536)).decode("utf-8", "replace") or "{}"
            data = json.loads(raw)
            ev = self.bridge.submit(
                data.get("event", data.get("e", "idle")),
                text=data.get("text", data.get("t", "")),
                bg=data.get("bg", ""),
                sp=data.get("sp", data.get("speed")),
                bl=data.get("bl"),
                p=data.get("p", data.get("progress")),
                label=data.get("label", ""),
            )
            self._send(200, {"ok": True, "event": ev})
        except ValueError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": repr(exc)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18894)
    ap.add_argument("--host", default=None, help="device address; default from settings.json or clawd-mochi.local")
    ap.add_argument("--stock-port", type=int, default=18892)
    ap.add_argument("--terminal", action="store_true", help="allow hook text to be typed on the pet's terminal view")
    ap.add_argument("--canvas", action="store_true", help="allow hook progress to be drawn on the pet's canvas view")
    ap.add_argument("--no-stock", action="store_true",
                    help="do not feed the stock control center on 18892 (fully replace its hooks)")
    args = ap.parse_args()

    host = args.host
    if not host:
        try:
            import os
            cfg = os.path.join(os.environ.get("APPDATA", ""), "ClawdMochi", "settings.json")
            with open(cfg, "r", encoding="utf-8") as fh:
                host = json.load(fh).get("host") or "clawd-mochi.local"
        except Exception:  # noqa: BLE001
            host = "clawd-mochi.local"

    dev = Device(host)
    st = dev.state()
    print(f"[bridge] device {dev.base} -> {'online' if st else 'OFFLINE (will retry)'} {json.dumps(st)}")
    Handler.bridge = Bridge(dev, args.stock_port, args.terminal, args.canvas, not args.no_stock)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    print(f"[bridge] listening on http://127.0.0.1:{args.port}  "
          f"terminal={'on' if args.terminal else 'off'} canvas={'on' if args.canvas else 'off'} "
          f"stock={'off' if args.no_stock else 'on'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
