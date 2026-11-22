#!/usr/bin/env python3
"""CS2 -> Clawd-Mochi: 击杀/死亡/回合 反应动画（Game State Integration）。

原理
----
CS2 官方支持 Game State Integration（GSI）：游戏会把你指定的本地 HTTP 地址
当作“事件输出口”，把整份对局状态 JSON POST 过来。只要在
    <CS2>/game/csgo/cfg/gamestate_integration_*.cfg
放一个 cfg 指向本脚本，就能拿到 kills / deaths / 武器 / 爆头 / HP / 回合结果。

本脚本监听 127.0.0.1:18895，收到 JSON 后做差分，再调用桌宠自己的 HTTP 接口
播动画（设备地址默认从 %APPDATA%\\ClawdMochi\\settings.json 读）。

层级说明（和 README 里一致）
----------------------------
  CS2 --GSI POST--> 本脚本 :18895 --HTTP--> 桌宠
  桌宠自带的 Clawd-Mochi.exe（18892）只认 7 个状态名；本脚本直接调设备接口，
  所以能用 13 个事件名 + 背景色 + 动画速度 + 终端文字 + 画布。

用法
----
    python cs2_mochi.py                       # 默认：击杀→“已完成”动画 + 底色闪光
    python cs2_mochi.py --text                # 再在终端视图打字幕（KILL +1 AK47）
    python cs2_mochi.py --anim error          # 换成“出错了”动画
    python cs2_mochi.py --dry-run             # 只打印，不动设备（联调用）
    python cs2_mochi.py --self-test           # 用内置假数据跑一遍检测逻辑
    python cs2_mochi.py --verbose             # 打印每条 GSI 与设备返回

安装 cfg（只需一次，重启 CS2 生效）：
    把 ext/cs2/gamestate_integration_clawdmochi.cfg 复制到
    D:\\Program Files (x86)\\Steam\\steamapps\\common\\Counter-Strike Global Offensive\\game\\csgo\\cfg\\

注意
----
* GSI 的 cfg 只在游戏启动时读取，所以装完必须重启 CS2（“下一次进游戏”生效）。
* GSI 是官方功能，不涉及注入/修改游戏，不会影响 VAC。
* 设备离线不会影响游戏：所有异常都被吞掉，GSI 请求永远返回 200。
* 想不靠游戏先看效果：GET /replay?kind=kill&tier=3 就能手动触发一次。
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from mochi_bridge import Device  # noqa: E402

# ---------------------------------------------------------------- 武器短名 ----
WEAPON = {
    "knife": "KNIFE", "knife_t": "KNIFE", "bayonet": "KNIFE",
    "ak47": "AK47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S", "awp": "AWP",
    "ssg08": "SSG08", "scar20": "SCAR-20", "g3sg1": "G3SG1", "aug": "AUG",
    "sg556": "SG553", "famas": "FAMAS", "galilar": "GALIL",
    "mac10": "MAC-10", "mp9": "MP9", "mp7": "MP7", "mp5sd": "MP5-SD",
    "ump45": "UMP-45", "p90": "P90", "bizon": "PP-BIZON", "m249": "M249",
    "negev": "NEGEV", "nova": "NOVA", "xm1014": "XM1014", "sawedoff": "SAWED-OFF",
    "mag7": "MAG-7", "glock": "GLOCK", "hkp2000": "P2000", "usp_silencer": "USP-S",
    "p250": "P250", "tec9": "TEC-9", "fiveseven": "FIVE-SEVEN", "deagle": "DEAGLE",
    "revolver": "R8", "elite": "DUALIES", "cz75a": "CZ75-AUTO", "taser": "ZEUS",
    "hegrenade": "HE", "flashbang": "FLASH", "smokegrenade": "SMOKE",
    "molotov": "MOLLY", "incgrenade": "INC", "decoy": "DECOY", "c4": "C4",
}

# 连杀档位：(名称, 底色)
TIERS = {
    1: ("KILL", "00FF66"),
    2: ("DOUBLE KILL", "FFC400"),
    3: ("TRIPLE KILL", "FF6A00"),
    4: ("QUAD KILL", "FF2D00"),
    5: ("ACE", "FF00FF"),
}


def weapon_label(name: str) -> str:
    n = (name or "").lower()
    if n.startswith("weapon_"):
        n = n[7:]
    return WEAPON.get(n, n.upper().replace("_", "-")[:12])


def active_weapon(weapons) -> str:
    """GSI 的 player.weapons 是 {"weapon_0": {...}, ...} 的字典。"""
    if not isinstance(weapons, dict):
        return ""
    found = ""
    for w in weapons.values():
        if not isinstance(w, dict):
            continue
        st = (w.get("state") or "").lower()
        if st == "active":
            return weapon_label(w.get("name", ""))
        if st in ("reloading", "silenced") and not found:
            found = weapon_label(w.get("name", ""))
    return found


# ------------------------------------------------------------------ 差分器 ----
class Analyzer:
    """把 GSI 的连续快照差分成人可读的事件列表。"""

    def __init__(self, window: float = 4.5):
        self.window = window
        self.kills_total = 0
        self.deaths_total = 0
        self.events = 0
        self.last = "startup"
        self.reset("startup")

    def reset(self, why: str = ""):
        self.prev: dict = {}
        self.hp = None
        self.kills = None          # None = 还没拿到基线，不能把首帧当击杀
        self.deaths = None
        self.dead = False
        self.map_name = ""
        self.round_no = None
        self.round_over = False
        self.kill_times: list[float] = []
        self.round_kills = 0
        self.streak = 0
        if why:
            self.last = "reset:" + why

    # -- 主入口 -------------------------------------------------------
    def feed(self, data: dict) -> list[dict]:
        player = data.get("player") or {}
        activity = (player.get("activity") or "").lower()
        mapinfo = data.get("map") or {}
        rnd = data.get("round") or {}
        pstate = player.get("state") or {}
        mstats = player.get("match_stats") or {}
        out: list[dict] = []

        # 换图 -> 全部重来
        mname = mapinfo.get("name") or ""
        if mname and self.map_name and mname != self.map_name:
            self.reset("map " + mname)
        if mname:
            self.map_name = mname

        # 只在真正打的时候反应
        if activity and activity not in ("playing", "textinput"):
            return []

        # 新回合
        rn = mapinfo.get("round")
        phase = (rnd.get("phase") or mapinfo.get("phase") or "").lower()
        if rn is not None and rn != self.round_no:
            self.round_no = rn
            self.round_over = False
            self.round_kills = 0
            self.kill_times = []
            self.dead = False
        if phase in ("freezetime", "live") and self.round_over:
            self.round_over = False
            self.round_kills = 0
            self.kill_times = []
            self.dead = False

        # ---- 爆头：round_killhs 增长（要在更新基线之前比较）----
        rk_hs = pstate.get("round_killhs")
        hs_flag = False
        if isinstance(rk_hs, int):
            prev_hs = self.prev.get("round_killhs")
            hs_flag = isinstance(prev_hs, int) and rk_hs > prev_hs

        # ---- 击杀：match_stats.kills 增长 ----
        kills = mstats.get("kills")
        if isinstance(kills, int):
            if self.kills is not None and kills > self.kills:
                for _ in range(kills - self.kills):
                    out.append(self._on_kill(player, hs_flag))
            self.kills = kills
        if isinstance(rk_hs, int):
            self.prev["round_killhs"] = rk_hs

        # ---- 死亡：deaths 增长 或 HP 归零（两条路径只算一次）----
        died = False
        deaths = mstats.get("deaths")
        if isinstance(deaths, int):
            if self.deaths is not None and deaths > self.deaths:
                died = True
            self.deaths = deaths
            self.deaths_total = max(self.deaths_total, deaths)
        hp = pstate.get("health")
        if isinstance(hp, int):
            if hp == 0 and isinstance(self.hp, int) and self.hp > 0:
                died = True
            if hp > 0:
                self.dead = False
            self.hp = hp
        if died and not self.dead:
            self.dead = True
            self.streak = 0
            out.append({"kind": "death", "text": "DEAD", "bg": "220000", "hold": 1200})

        # ---- 回合结束 ----
        if phase == "over" and not self.round_over:
            self.round_over = True
            win = (rnd.get("win_team") or "").upper()
            team = (player.get("team") or "").upper()
            if win and team:
                out.append({"kind": "round", "win": win == team, "round": self.round_no,
                            "hold": 1800})

        for ev in out:
            self.events += 1
        if out:
            self.last = out[-1]["kind"]
        return out

    # -- 单个击杀 -----------------------------------------------------
    def _on_kill(self, player, hs: bool = False) -> dict:
        now = time.time()
        self.round_kills += 1
        self.streak += 1
        self.kills_total += 1
        self.kill_times = [t for t in self.kill_times if now - t <= self.window] + [now]
        tier = min(len(self.kill_times), 5)
        name, color = TIERS[tier]

        w = active_weapon(player.get("weapons"))
        # 单杀时按“怎么杀的”换文案：刀杀 / 爆头 / 普通击杀
        base = name
        if tier == 1:
            if w == "KNIFE":
                base = "KNIFE KILL"
            elif hs:
                base = "HEADSHOT"
        parts = [base]
        if w and w not in base:
            parts.append(w)
        if hs and "HEADSHOT" not in base:
            parts.append("HS")
        text = "  ".join(parts)
        return {
            "kind": "kill", "tier": tier, "label": base, "bg": color,
            "weapon": w, "hs": hs, "text": text,
            "round_kills": self.round_kills, "total": self.kills_total,
            "streak": self.streak,
        }


# ------------------------------------------------------------------ 播放器 ----
class Fx:
    """把事件翻译成桌宠动作。串行执行，避免终端/画布互相打架。"""

    def __init__(self, dev: Device, args):
        self.dev = dev
        self.args = args
        self.q: queue.Queue = queue.Queue(maxsize=64)
        self.played = 0
        self.errors = 0
        self.last = ""
        self.term_open = False
        self.canvas_open = False
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, job: dict):
        # 连杀时宁可丢旧动画也不要延迟：队列里堆太多就把最旧的丢掉
        while self.q.qsize() >= max(1, int(self.args.max_queue)):
            try:
                self.q.get_nowait()
                self.q.task_done()
            except queue.Empty:
                break
        try:
            self.q.put_nowait(job)
        except queue.Full:
            return
        if self.args.verbose:
            print(f"[fx] queued {job.get('kind')} {job.get('text', '')}".rstrip(), flush=True)

    # -- worker -------------------------------------------------------
    def _run(self):
        while True:
            job = self.q.get()
            try:
                self._play(job)
                self.played += 1
                self.last = job.get("kind", "")
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                if self.args.verbose:
                    print(f"[fx] error {exc!r}", flush=True)
            finally:
                self.q.task_done()

    def _event(self, name: str):
        if not name or name == "none":
            return 0
        try:
            with urllib.request.urlopen(self.dev.base + "/event?s=" + urllib.parse.quote(name),
                                        timeout=1.5) as r:
                return r.status
        except Exception:  # noqa: BLE001
            return 0

    def _slot(self, name: str, hold_ms: int = 0):
        """播放设备上的自定义动画槽：/event?s=<slot>&h=<毫秒>（自写固件支持任意多槽位）。"""
        if not name:
            return 0
        try:
            url = self.dev.base + "/event?s=" + urllib.parse.quote(name)
            if hold_ms > 0:
                url += "&h=" + str(int(hold_ms))
            with urllib.request.urlopen(url, timeout=1.5) as r:
                return r.status
        except Exception:  # noqa: BLE001
            return 0

    def _speak(self, text: str):
        """终端视图打字（会接管屏幕）。"""
        try:
            if self.canvas_open:
                self.dev.canvas_on(False)
                self.canvas_open = False
            st = self.dev.state()
            if not st.get("term"):
                self.dev.cmd("d")
                time.sleep(0.3)
            self.term_open = True
            self.dev.type_line(text[:80] + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _splash(self, color: str):
        """画布上画一个准星（会接管屏幕）。"""
        try:
            if not self.canvas_open:
                self.dev.canvas_on(True)
                time.sleep(0.35)
                self.canvas_open = True
            self.dev.draw_clear("000000")
            cx, cy = 120, 90
            for r in (10, 26):
                self.dev.stroke([(cx - r, cy), (cx + r, cy)], color)
                self.dev.stroke([(cx, cy - r), (cx, cy + r)], color)
            for i in range(4):
                x = 20 + i * 60
                self.dev.stroke([(x, 160), (x, 168)], color)
        except Exception:  # noqa: BLE001
            pass

    def _play(self, job: dict):
        a = self.args
        t0 = time.time()
        kind = job.get("kind")
        color = job.get("bg")

        if a.dry_run:
            print(f"[dry] {json.dumps(job, ensure_ascii=False)}", flush=True)
            return

        # 自定义动画槽（自写固件）：整屏动画由设备自己播，播完自动回待机
        if getattr(a, "slots", False):
            slot = None
            if kind == "kill":
                slot = a.slot_map.get(max(1, int(job.get("tier", 1))))
                tier = max(1, int(job.get("tier", 1)))
                hold = a.kill_hold + a.kill_hold_step * (tier - 1)
            elif kind == "death":
                slot = a.death_slot
                hold = job.get("hold", a.hold)
            elif kind == "round" and a.round_fx:
                slot = a.roundwin_slot if job.get("win") else a.roundlose_slot
                hold = job.get("hold", a.hold)
            else:
                hold = job.get("hold", a.hold)
            if slot:
                self._slot(slot, hold)
                if a.verbose:
                    print(f"[fx] slot={slot} hold={hold}ms bg={color}", flush=True)
                self.last = {"at": time.time(), "job": job, "slot": slot}
                time.sleep(max(0.3, hold / 1000.0))
                self._event(a.rest_event)
                if a.verbose:
                    print(f"[fx] restored, total +{time.time()-t0:.2f}s", flush=True)
                return

        if color and a.bg:
            self.dev.bg(color)
            if a.bg_lead > 0:          # 先让底色在普通眼视图上露一会儿
                time.sleep(a.bg_lead / 1000.0)
        if a.speed:
            self.dev.anim_speed(a.fx_speed)

        if kind == "kill":
            anim = getattr(a, "anim_map", {}).get(job.get("tier"), a.anim)
            if a.verbose:
                print(f"[fx] play tier={job.get('tier')} anim={anim} bg={color}", flush=True)
            if anim != "none":
                self._event(anim)
                if a.text:
                    time.sleep(0.45)
            if a.canvas:
                self._splash(color or "00FF66")
            if a.text and job.get("text") and job.get("tier", 1) >= a.text_min_tier:
                self._speak(job["text"])

        elif kind == "death":
            if a.anim != "none":
                self._event(a.death_anim)
            if a.canvas and a.bg:
                self._splash("FF2D00")
            if a.text:
                self._speak("DEAD")

        elif kind == "round":
            if a.round_fx:
                if a.anim != "none":
                    self._event(a.anim if job.get("win") else a.death_anim)
                if a.text:
                    self._speak("ROUND WIN" if job.get("win") else "ROUND LOST")

        if kind == "kill":
            tier = max(1, int(job.get("tier", 1)))
            hold = a.kill_hold + a.kill_hold_step * (tier - 1)
        else:
            hold = job.get("hold", a.hold)
        if a.verbose:
            print(f"[fx] hold {hold}ms (anim started at +{time.time()-t0:.2f}s)", flush=True)
        time.sleep(max(0.3, hold / 1000.0))
        self._restore()
        if a.verbose:
            print(f"[fx] restored, total +{time.time()-t0:.2f}s", flush=True)

    def _restore(self):
        a = self.args
        had_takeover = self.term_open or self.canvas_open
        try:
            if self.canvas_open:
                self.dev.canvas_on(False)
                self.canvas_open = False
            if self.term_open or self.dev.term:
                self.dev.cmd("q")
                self.term_open = False
            if a.bg:
                self.dev.bg(a.restore_bg)
            if a.speed:
                self.dev.anim_speed(1)
            if a.anim != "none":
                self._event(a.rest_event)
            if had_takeover:
                self.dev.cmd("w")     # 退出终端/画布后强制回普通眼视图
        except Exception:  # noqa: BLE001
            pass

    def status(self) -> dict:
        return {
            "played": self.played, "errors": self.errors, "queued": self.q.qsize(),
            "last": self.last, "device": self.dev.base,
            "device_connected": self.dev.connected,
            "anim": getattr(self.args, "anim", ""),
            "anim_map": getattr(self.args, "anim_map", {}),
            "slots": {str(k): v for k, v in (getattr(self.args, "slot_map", {}) or {}).items()},
            "fx_speed": getattr(self.args, "fx_speed", 1),
            "kill_hold": getattr(self.args, "kill_hold", 2400),
        }


# ------------------------------------------------------------------ 状态页 ----
DASHBOARD = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clawd-Mochi × CS2</title>
<style>
:root{color-scheme:dark}
body{margin:0;padding:24px;background:#14161a;color:#e6e6e6;
     font:14px/1.5 -apple-system,"Segoe UI",system-ui,sans-serif}
h1{margin:0 0 4px;font-size:20px;font-weight:600}
.sub{color:#8a8f98;font-size:12px;margin-bottom:18px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.card{background:#1c1f26;border:1px solid #2a2f3a;border-radius:10px;padding:10px 12px}
.k{color:#8a8f98;font-size:11px;letter-spacing:.04em;text-transform:uppercase}
.v{font-size:18px;font-weight:600;margin-top:2px;word-break:break-all}
.ok{color:#3ddc84}.bad{color:#ff5d5d}
.btns{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
button{background:#262b35;color:#e6e6e6;border:1px solid #39404d;border-radius:8px;
       padding:7px 12px;font-size:13px;cursor:pointer}
button:hover{background:#303742}
pre{background:#1c1f26;border:1px solid #2a2f3a;border-radius:10px;padding:12px;
    overflow:auto;font-size:12px;color:#9aa4b2;max-height:300px}
a{color:#6cb6ff}
</style></head><body>
<h1>Clawd-Mochi × CS2</h1>
<div class="sub">状态页 · 自动刷新 1 s · 桥 <code>127.0.0.1:18895</code>
  · <a href="http://127.0.0.1:18893/" target="_blank">控制中心</a>
  · <a href="http://clawd-mochi.local/" target="_blank">设备网页</a></div>

<div class="cards">
  <div class="card"><div class="k">桥</div><div class="v ok" id="bridge">…</div></div>
  <div class="card"><div class="k">桌宠连接</div><div class="v" id="device">…</div></div>
  <div class="card"><div class="k">GSI 数据</div><div class="v" id="gsi">…</div></div>
  <div class="card"><div class="k">已播放</div><div class="v" id="played">…</div></div>
  <div class="card"><div class="k">队列</div><div class="v" id="queued">…</div></div>
  <div class="card"><div class="k">击杀 / 死亡</div><div class="v" id="kd">…</div></div>
  <div class="card"><div class="k">回合 / 地图</div><div class="v" id="round">…</div></div>
  <div class="card"><div class="k">错误</div><div class="v" id="errors">…</div></div>
</div>

<div class="btns">
  <button data-kind="kill" data-tier="1">单杀</button>
  <button data-kind="kill" data-tier="2">双杀</button>
  <button data-kind="kill" data-tier="3">三杀</button>
  <button data-kind="kill" data-tier="4">四杀</button>
  <button data-kind="kill" data-tier="5">ACE</button>
  <button data-kind="death">死亡</button>
  <button data-kind="round" data-win="1">回合胜</button>
  <button data-kind="round" data-win="0">回合负</button>
</div>
<div class="sub" id="animmap">当前动画映射：-</div>
<pre id="raw">等待数据…</pre>

<script>
const $ = id => document.getElementById(id);
function set(id, text, cls){ const el = $(id); el.textContent = text;
  if (cls !== undefined){ el.className = 'v ' + cls; } }
async function poll(){
  try{
    const r = await fetch('/status', {cache:'no-store'});
    const d = await r.json();
    const fx = d.fx || {};
    set('bridge', '在线', 'ok');
    set('device', fx.device_connected ? '已连接' : '未连接', fx.device_connected ? 'ok' : 'bad');
    set('gsi', d.gsi_connected ? (d.gsi_age + ' s 前') : '无（游戏未开 / 未重启）',
        d.gsi_connected ? 'ok' : 'bad');
    set('played', String(fx.played ?? 0));
    set('queued', String(fx.queued ?? 0));
    set('kd', (d.kills ?? 0) + ' / ' + (d.deaths ?? 0));
    set('round', (d.round ?? '-') + ' · ' + (d.map || '-'));
    set('errors', String(fx.errors ?? 0), (fx.errors ? 'bad' : ''));
    const am = fx.anim_map || {};
    const names = {done:'已完成', error:'出错了', thinking:'思考', coding:'工作中',
                   waiting:'等待你', idle:'待机', sleep:'休息', none:'不播'};
    const tierName = {1:'单杀',2:'双杀',3:'三杀',4:'四杀',5:'ACE'};
    const parts = Object.keys(am).sort().map(k => tierName[k] + '=' + (names[am[k]] || am[k]));
    $('animmap').textContent = '当前动画映射：' + (parts.length ? parts.join('  ·  ') : ('全部 ' + (names[fx.anim] || fx.anim)));
    $('raw').textContent = JSON.stringify(d, null, 2);
  }catch(e){
    set('bridge', '离线', 'bad');
    $('raw').textContent = '无法连接 127.0.0.1:18895 —— 桥没在跑？双击 ext\\\\cs2\\\\start.bat';
  }
}
document.querySelectorAll('button[data-kind]').forEach(b => {
  b.onclick = () => {
    const k = b.dataset.kind, t = b.dataset.tier, w = b.dataset.win;
    let url = '/replay?kind=' + k;
    if (t) url += '&tier=' + t;
    if (w !== undefined) url += '&win=' + w;
    fetch(url).then(r => r.json()).then(j => { $('raw').textContent = '已触发: ' + JSON.stringify(j); });
  };
});
poll(); setInterval(poll, 1000);
</script>
</body></html>"""


# -------------------------------------------------------------------- HTTP ----
class Handler(BaseHTTPRequestHandler):
    analyzer: Analyzer = None
    fx: Fx = None
    verbose = False
    last_gsi = 0.0
    server_version = "clawd-mochi-cs2/1.0"

    def log_message(self, fmt, *args):
        if self.verbose:
            print("[gsi] " + (fmt % args), flush=True)

    def _reply(self, code: int, payload=None):
        body = json.dumps(payload or {"ok": True}, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        try:
            n = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(min(n, 1 << 20)) or b"{}"
            data = json.loads(raw.decode("utf-8", "replace"))
            Handler.last_gsi = time.time()
            if self.verbose:
                p = data.get("player") or {}
                ms = p.get("match_stats") or {}
                st = p.get("state") or {}
                print(f"[gsi] {self.path} act={p.get('activity')} k={ms.get('kills')} "
                      f"d={ms.get('deaths')} hp={st.get('health')} "
                      f"rk={st.get('round_kills')} phase={(data.get('round') or {}).get('phase')}",
                      flush=True)
            for job in self.analyzer.feed(data):
                self.fx.submit(job)
        except Exception as exc:  # noqa: BLE001
            if self.verbose:
                print(f"[gsi] bad payload: {exc!r}", flush=True)
        self._reply(200)   # GSI 只关心 200

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/status", "/health"):
            age = None
            if Handler.last_gsi:
                age = round(time.time() - Handler.last_gsi, 1)
            self._reply(200, {
                "ok": True, "fx": self.fx.status(),
                "kills": self.analyzer.kills_total, "deaths": self.analyzer.deaths_total,
                "round": self.analyzer.round_no, "map": self.analyzer.map_name,
                "last": self.analyzer.last, "events": self.analyzer.events,
                "gsi_age": age, "gsi_connected": bool(age is not None and age < 15),
            })
            return
        if path in ("/", "/index.html"):
            body = DASHBOARD.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/replay":     # 不依赖游戏的手动触发
            qs = urllib.parse.parse_qs(parsed.query)
            kind = (qs.get("kind", ["kill"])[0] or "kill").lower()
            tier = int(qs.get("tier", ["1"])[0] or 1)
            job: dict = {"kind": kind, "hold": 1200}
            if kind == "kill":
                name, color = TIERS[min(max(tier, 1), 5)]
                job.update({"tier": tier, "label": name, "bg": color,
                            "text": name})
            elif kind == "death":
                job.update({"bg": "220000", "hold": 1200})
            elif kind == "round":
                job.update({"win": (qs.get("win", ["1"])[0] or "1") == "1", "hold": 1800})
            self.fx.submit(job)
            self._reply(200, {"ok": True, "job": job})
            return
        self._reply(404, {"ok": False, "error": "not found"})


# -------------------------------------------------------------------- main ----
def demo_payload(stats=None, state=None, hp=100, weapon="weapon_ak47",
                 map_round=1, phase="live", win_team=None, team="CT", activity="playing"):
    return {
        "provider": {"name": "Counter-Strike: Global Offensive", "appid": 730},
        "map": {"mode": "competitive", "name": "de_dust2", "phase": "live", "round": map_round},
        "round": {"phase": phase, "win_team": win_team},
        "player": {
            "steamid": "76561190000000000", "name": "demo", "team": team,
            "activity": activity,
            "state": dict({"health": hp, "armor": 100, "round_kills": 0, "round_killhs": 0},
                          **(state or {})),
            "weapons": {"weapon_0": {"name": weapon, "state": "active"}},
            "match_stats": dict({"kills": 0, "assists": 0, "deaths": 0}, **(stats or {})),
        },
    }


def self_test() -> int:
    a = Analyzer()
    seq = [
        ("进游戏", demo_payload()),
        ("第1杀(AK爆头)", demo_payload(stats={"kills": 1}, state={"round_killhs": 1})),
        ("第2杀", demo_payload(stats={"kills": 2}, state={"round_killhs": 1})),
        ("第3杀", demo_payload(stats={"kills": 3}, state={"round_killhs": 1})),
        ("第4杀", demo_payload(stats={"kills": 4}, state={"round_killhs": 1})),
        ("第5杀(ACE)", demo_payload(stats={"kills": 5}, state={"round_killhs": 1})),
        ("死亡", demo_payload(stats={"kills": 5, "deaths": 1}, hp=0)),
        ("下一回合", demo_payload(map_round=2, phase="freezetime", stats={"kills": 5, "deaths": 1})),
        ("回合结束(赢)", demo_payload(map_round=2, phase="over", win_team="CT",
                                    stats={"kills": 5, "deaths": 1})),
    ]
    for label, payload in seq:
        evs = a.feed(payload)
        desc = []
        for e in evs:
            if e["kind"] == "kill":
                desc.append(f"kill[{e['label']}|{e.get('weapon')}|{e['bg']}|hs={e['hs']}]")
            elif e["kind"] == "round":
                desc.append(f"round[win={e['win']}]")
            else:
                desc.append(e["kind"])
        print(f"  {label:16s} -> " + ("; ".join(desc) or "(无)"))
        time.sleep(0.05)
    ok = a.kills_total == 5 and a.deaths_total == 1 and a.events == 7
    print("\n检查：")
    print(f"  击杀 kills={a.kills_total} (期望 5)")
    print(f"  死亡 deaths={a.deaths_total} (期望 1)")
    print(f"  事件 events={a.events} (期望 7 = 5杀+1死+1回合)")
    print("结果：" + ("全部通过" if ok else "有不符合项"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="CS2 GSI -> Clawd-Mochi kill reactions")
    ap.add_argument("--port", type=int, default=18895)
    ap.add_argument("--host", default=None, help="桌宠地址，默认从 settings.json 读")
    ap.add_argument("--slots", action="store_true",
                    help="播放设备上的自定义动画槽（自写固件；/event?s=kill1&h=毫秒）")
    ap.add_argument("--slot-map", default="1=kill1,2=kill2,3=kill3,4=kill4,5=kill5",
                    help="连杀档位 -> 槽位名，默认 kill1..kill5")
    ap.add_argument("--death-slot", default="death", help="死亡时播放的槽位")
    ap.add_argument("--roundwin-slot", default="roundwin", help="回合胜的槽位")
    ap.add_argument("--roundlose-slot", default="roundlose", help="回合负的槽位")
    ap.add_argument("--anim", default="done",
                    choices=["done", "error", "thinking", "coding", "waiting", "idle",
                             "sleep", "none"],
                    help="击杀时播放哪个桌宠动画（默认 done=已完成）")
    ap.add_argument("--anim-map", default="",
                    help="按连杀档位分别指定动画，例如 '1=done,2=coding,3=thinking,4=waiting,5=error'"
                         "（写了这个就以它为准，--anim 只作兜底）")
    ap.add_argument("--death-anim", default="error", help="死亡时播放的动画（默认 error=出错了）")
    ap.add_argument("--fx-speed", type=int, default=1, choices=[1, 2, 3],
                    help="播放动画时把动画速度设成几档：1=慢(默认，最耐看) 2=正常 3=快")
    ap.add_argument("--kill-hold", type=int, default=2400,
                    help="单杀动画停留毫秒（默认 2400；想更久就调大，比如 4000）")
    ap.add_argument("--kill-hold-step", type=int, default=400,
                    help="每多一档连杀额外停留毫秒（默认 400）")
    ap.add_argument("--bg-lead", type=int, default=600,
                    help="先展示底色多少毫秒再播动画（默认 600；0=不单独闪底色）")
    ap.add_argument("--rest-event", default="idle", help="收尾回到哪个状态（默认 idle）")
    ap.add_argument("--restore-bg", default="cd3400", help="收尾恢复的底色（默认待机色 cd3400）")
    ap.add_argument("--hold", type=int, default=1400, help="动画停留毫秒（默认 1400）")
    ap.add_argument("--bg", action="store_true", default=True, help="允许改底色（默认开）")
    ap.add_argument("--no-bg", dest="bg", action="store_false")
    ap.add_argument("--speed", action="store_true", default=True, help="允许改动画速度（默认开）")
    ap.add_argument("--no-speed", dest="speed", action="store_false")
    ap.add_argument("--text", action="store_true", help="在终端视图打字幕（会接管屏幕）")
    ap.add_argument("--text-min-tier", type=int, default=1,
                    help="几连杀以上才打字幕，2=只有双杀起才显示（默认 1）")
    ap.add_argument("--canvas", action="store_true", help="在画布上画准星（会接管屏幕）")
    ap.add_argument("--round-fx", action="store_true", help="回合胜负也播动画")
    ap.add_argument("--max-queue", type=int, default=2, help="播放队列上限，连杀时丢弃旧动画")
    ap.add_argument("--dry-run", action="store_true", help="只打印不执行")
    ap.add_argument("--self-test", action="store_true", help="跑内置检测用例后退出")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # --anim-map "1=done,2=coding,..." -> {1: "done", 2: "coding", ...}
    if args.anim_map:
        amap: dict[int, str] = {}
        for part in args.anim_map.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                k, v = k.strip(), v.strip().lower()
                if k.isdigit() and v:
                    amap[int(k)] = v
        args.anim_map = amap
    else:
        args.anim_map = {}

    if args.slot_map:
        smap: dict[int, str] = {}
        for part in args.slot_map.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                k, v = k.strip(), v.strip()
                if k.isdigit() and v:
                    smap[int(k)] = v
        args.slot_map = smap
    else:
        args.slot_map = {}

    if args.self_test:
        return self_test()

    host = args.host
    if not host:
        try:
            cfg = os.path.join(os.environ.get("APPDATA", ""), "ClawdMochi", "settings.json")
            with open(cfg, "r", encoding="utf-8") as fh:
                host = json.load(fh).get("host") or "clawd-mochi.local"
        except Exception:  # noqa: BLE001
            host = "clawd-mochi.local"

    dev = Device(host)
    st = dev.state()
    print(f"[cs2] 桌宠 {dev.base} -> {'在线' if st else '离线(播放时重试)'} "
          f"{json.dumps(st, ensure_ascii=False)}", flush=True)

    Handler.analyzer = Analyzer()
    Handler.fx = Fx(dev, args)
    Handler.verbose = args.verbose
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    print(f"[cs2] GSI 监听 http://127.0.0.1:{args.port}  击杀动画={args.anim} "
          f"字幕={'on' if args.text else 'off'} 画布={'on' if args.canvas else 'off'} "
          f"底色={'on' if args.bg else 'off'} 速度={'on' if args.speed else 'off'}", flush=True)
    print("[cs2] cfg 要放到 CS2 的 game/csgo/cfg/ 下，并重启游戏才生效", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
