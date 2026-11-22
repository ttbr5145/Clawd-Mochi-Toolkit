#include "pet.h"
#include "display.h"
#include "slot_labels.h"
#include "config.h"
#include "assets.h"
#include <LittleFS.h>
#include <Preferences.h>

namespace pet {

uint8_t state = ST_IDLE;
uint8_t view = VIEW_EYES;
uint8_t speed = 1;
uint16_t bgColor = 0xC9A0;
bool backlight = true;

static const uint8_t *const PILLTXT[ANIM_N] = {
    PILLTXT_IDLE, PILLTXT_THINKING, PILLTXT_WORKING, PILLTXT_WAITING,
    PILLTXT_DONE, PILLTXT_ERROR, PILLTXT_SLEEP};

static const uint16_t SPEED_NUM[4] = {10, 10, 7, 4};  // 1=x1.0 2=x1.43 3=x2.5
static const uint16_t SPEED_DEN[4] = {10, 10, 10, 10};

enum Src : uint8_t { SRC_ANIM = 0, SRC_BASE = 1, SRC_SLOT_IMG = 2, SRC_CMA = 3 };

static uint8_t animIdx = ANIM_IDLE;
static uint16_t frame = 0;
static uint32_t frameDue = 0;
static uint8_t src = SRC_ANIM;
static char slotName[24] = {0};
static uint32_t slotUntil = 0;
static uint32_t lastEventAt = 0;
static uint32_t doneAt = 0;

// 终端
static char termBuf[192] = {0};
static size_t termLen = 0;
static bool cursorOn = false;
static uint32_t cursorDue = 0;
static uint16_t termBg = 0x10C4;

// 画布
static uint16_t canvasBg = 0x0000;
static bool canvasOnFlag = false;

// 自定义槽位动画（CMA1）
struct Cma {
  File f;
  bool open = false;
  uint16_t pal_n = 0, frame_n = 0, bg_idx = 0;
  uint16_t *pal = nullptr;
  uint32_t *cum = nullptr;
  uint16_t *dur = nullptr;
  uint32_t rectBase = 0;
  uint16_t curFrame = 0;
};
static Cma cma;

static const uint16_t BG_SLEEP = 0x0000;

const char *stateName(uint8_t st) {
  static const char *names[] = {"idle", "thinking", "working", "waiting", "done", "error", "sleep", "slot"};
  return st <= ST_SLOT ? names[st] : "?";
}

const __FlashStringHelper *stateLabel(uint8_t st) {
  switch (st) {
    case ST_IDLE: return F("idle");
    case ST_THINK: return F("thinking");
    case ST_WORK: return F("working");
    case ST_WAIT: return F("waiting");
    case ST_DONE: return F("done");
    case ST_ERROR: return F("error");
    case ST_SLEEP: return F("sleep");
    default: return F("slot");
  }
}

// ───────────────────────── 自定义图片 / 槽位 ─────────────────────────

bool baseExists(uint8_t st) { return LittleFS.exists(String("/base/") + st + ".rgb"); }
bool slotExists(const char *name) {
  String n(name);
  return LittleFS.exists("/slot/" + n + ".rgb") || LittleFS.exists("/slot/" + n + ".cma");
}
uint32_t slotCount() {
  File d = LittleFS.open("/slot");
  if (!d || !d.isDirectory()) return 0;
  uint32_t n = 0;
  File e = d.openNextFile();
  while (e) {
    String nm = e.name();
    if (nm.endsWith(".rgb") || nm.endsWith(".cma")) n++;
    e = d.openNextFile();
  }
  return n;
}

static bool loadImageIntoStage(const String &path) {
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  uint32_t total = f.size();
  if (total != ANIM_STAGE_W * ANIM_STAGE_H * 2) { f.close(); return false; }
  uint8_t *dst = (uint8_t *)scr::stage().getBuffer();
  size_t got = 0;
  while (got < total) {
    size_t n = f.read(dst + got, total - got > 4096 ? 4096 : total - got);
    if (!n) break;
    got += n;
  }
  f.close();
  return got == total;
}

static void cmaClose() {
  if (cma.f) cma.f.close();
  free(cma.pal); cma.pal = nullptr;
  free(cma.cum); cma.cum = nullptr;
  free(cma.dur); cma.dur = nullptr;
  cma.open = false;
}

static bool cmaOpen(const String &path) {
  cmaClose();
  cma.f = LittleFS.open(path, "r");
  if (!cma.f) return false;
  uint8_t hdr[16];
  if (cma.f.read(hdr, 16) != 16) { cmaClose(); return false; }
  if (memcmp(hdr, "CMA1", 4) != 0) { cmaClose(); return false; }
  cma.pal_n = hdr[6] | (hdr[7] << 8);
  cma.frame_n = hdr[8] | (hdr[9] << 8);
  cma.bg_idx = hdr[10] | (hdr[11] << 8);
  if (cma.pal_n == 0 || cma.pal_n > 256 || cma.frame_n == 0 || cma.frame_n > 512) { cmaClose(); return false; }
  cma.pal = (uint16_t *)malloc(2 * cma.pal_n);
  cma.cum = (uint32_t *)malloc(4 * (cma.frame_n + 1));
  cma.dur = (uint16_t *)malloc(2 * cma.frame_n);
  if (!cma.pal || !cma.cum || !cma.dur) { cmaClose(); return false; }
  if (cma.f.read((uint8_t *)cma.pal, 2 * cma.pal_n) != 2 * cma.pal_n) { cmaClose(); return false; }
  uint8_t ft[4];
  cma.cum[0] = 0;
  for (uint16_t i = 0; i < cma.frame_n; i++) {
    if (cma.f.read(ft, 4) != 4) { cmaClose(); return false; }
    cma.dur[i] = ft[0] | (ft[1] << 8);
    uint16_t rn = ft[2] | (ft[3] << 8);
    cma.cum[i + 1] = cma.cum[i] + rn;
  }
  cma.rectBase = 16 + 2 * cma.pal_n + 4 * cma.frame_n;
  cma.curFrame = 0;
  cma.open = true;
  return true;
}

static void cmaDrawFrame(uint16_t fr) {
  if (!cma.open) return;
  scr::fillStage(cma.pal[cma.bg_idx]);
  uint32_t n = cma.cum[fr + 1] - cma.cum[fr];
  uint32_t off = cma.rectBase + 5 * cma.cum[fr];
  uint8_t chunk[5 * 64];
  while (n) {
    size_t m = n > 64 ? 64 : n;
    if (!cma.f.seek(off)) break;
    if (cma.f.read(chunk, 5 * m) != 5 * m) break;
    for (size_t i = 0; i < m; i++) {
      const uint8_t *r = chunk + 5 * i;
      uint8_t pi = r[0];
      if (!pi) continue;
      scr::stage().fillRect(r[1], r[2], r[3], r[4], cma.pal[pi]);
    }
    off += 5 * m;
    n -= m;
  }
  scr::pushStage();
}

// ───────────────────────── 渲染 ─────────────────────────

static void drawAnimFrame(uint8_t idx, uint16_t f) {
  const AnimDef &a = ANIMS[idx];
  if (f >= a.frame_n) f = 0;
  uint16_t bg = (idx == ANIM_SLEEP) ? BG_SLEEP : bgColor;
  scr::fillStage(bg);
  uint32_t r0 = a.frame_rstart[f];
  uint16_t n = a.frame_rcount[f];
  for (uint16_t i = 0; i < n; i++) {
    const uint8_t *r = a.rects + 5 * (r0 + i);
    uint8_t pi = r[0];
    if (!pi) continue;
    scr::stage().fillRect(r[1], r[2], r[3], r[4], a.pal[pi]);
  }
}

// 眯眼：把纯黑像素（眼睛）纵向压成中间一条
static void squishEyes() {
  GFXcanvas16 &g = scr::stage();
  uint16_t *buf = g.getBuffer();
  const int W = ANIM_STAGE_W, H = ANIM_STAGE_H;
  for (int x = 0; x < W; x++) {
    int y0 = -1, y1 = -1;
    for (int y = 0; y < H; y++) {
      if (buf[y * W + x] == 0x0000) { if (y0 < 0) y0 = y; y1 = y; }
    }
    if (y0 < 0 || y1 - y0 < 6) continue;
    uint16_t fill = 0;
    int sy = (y0 - 6 >= 0) ? buf[(y0 - 6) * W + x] : 0;
    int sy2 = (y1 + 6 < H) ? buf[(y1 + 6) * W + x] : 0;
    fill = sy ? sy : sy2;
    if (!fill) fill = 0xD081;  // 身体色兜底
    int mid = (y0 + y1) / 2;
    for (int y = y0; y <= y1; y++) {
      if (y < mid - 2 || y > mid + 2) buf[y * W + x] = fill;
    }
  }
}

static void pillFor(uint8_t st, const char *slot, uint16_t bg, uint8_t animForDot) {
  uint16_t dot = PILL_DOT_COLOR[animForDot < ANIM_N ? animForDot : ANIM_IDLE];
  if (st == ST_SLOT) {
    const uint8_t *lb = slotLabelBits(slot);
    scr::showPill(bg, 0xFEB4, lb, lb ? nullptr : slot);
  } else {
    uint8_t a = st <= ST_SLEEP ? st : ANIM_IDLE;
    scr::showPill(bg, dot, PILLTXT[a], nullptr);
  }
}

static void pushWithPill(uint8_t st) {
  scr::pushStage();
  uint8_t a = (st == ST_SLEEP) ? ANIM_SLEEP : (st <= ST_SLEEP ? st : animIdx);
  uint16_t bg = (st == ST_SLEEP) ? BG_SLEEP : bgColor;
  pillFor(st, slotName, bg, a);
}

// 终端界面
static void drawTerminal(bool full) {
  GFXcanvas16 &g = scr::stage();
  if (full) {
    g.fillScreen(termBg);
    g.setTextSize(1);
    g.setTextColor(0x7BEF);
    g.setCursor(6, 4);
    g.print(F("Clawd-Mochi terminal  [q]=close"));
    g.drawFastHLine(0, 16, ANIM_STAGE_W, 0x3186);
  }
  // 清内容区
  g.fillRect(0, 18, ANIM_STAGE_W, ANIM_STAGE_H - 18 - 18, termBg);
  g.setTextSize(2);
  g.setTextColor(0xFFFF);
  const int charW = 12, lineH = 18;
  char line[220];
  memcpy(line, termBuf, termLen);
  line[termLen] = 0;
  String s = String("clawd:~$ ") + line;
  int perLine = ANIM_STAGE_W / charW;  // 20
  int y = 22;
  for (size_t i = 0; i < s.length() && y < ANIM_STAGE_H - 22; i += perLine) {
    String part = s.substring(i, i + perLine);
    g.setCursor(6, y);
    g.print(part);
    y += lineH;
  }
  // 光标
  if (cursorOn) {
    int used = s.length() % perLine;
    g.fillRect(6 + used * charW, y - lineH + 3, charW - 2, lineH - 5, 0xFFE0);
  }
  scr::pushStage();
  scr::showPill(termBg, 0xFEB4, PILLTXT_IDLE, nullptr);
}

// ───────────────────────── 对外操作 ─────────────────────────

void redraw() {
  if (src == SRC_SLOT_IMG) {
    if (!loadImageIntoStage(String("/base/0.rgb"))) { /* ignore */ }
    scr::pushStage();
    pillFor(state, slotName, bgColor, animIdx);
    return;
  }
  switch (view) {
    case VIEW_TERM: drawTerminal(true); break;
    case VIEW_CANVAS:
      scr::fillStage(canvasBg);
      scr::pushStage();
      pillFor(state, slotName, canvasBg, animIdx);
      break;
    default:
      if (src == SRC_BASE) {
        String p = String("/base/") + state + ".rgb";
        if (loadImageIntoStage(p)) { scr::pushStage(); pillFor(state, slotName, bgColor, state); }
        else { src = SRC_ANIM; drawAnimFrame(animIdx, frame); pushWithPill(state); }
      } else if (src == SRC_ANIM) {
        drawAnimFrame(animIdx, frame);
        if (view == VIEW_SQUISH) squishEyes();
        pushWithPill(state);
      } else if (src == SRC_CMA) {
        cmaDrawFrame(cma.curFrame);
        pillFor(ST_SLOT, slotName, bgColor, animIdx);
      }
      break;
  }
}

void setState(uint8_t st) {
  uint8_t prev = state;
  state = st;
  lastEventAt = millis();
  if (st == ST_DONE) doneAt = millis();
  if (st <= ST_SLEEP && baseExists(st)) {
    src = SRC_BASE;
    frame = 0;
  } else {
    src = SRC_ANIM;
    animIdx = (st <= ST_SLEEP) ? st : ANIM_IDLE;
    frame = 0;
  }
  frameDue = millis();
  // 从终端/画布视图切回眼睛
  if (view == VIEW_TERM) { view = VIEW_EYES; canvasOnFlag = false; }
  if (st == ST_ERROR || st == ST_DONE) {
    // 保持当前 view（终端里的事件不影响终端）
  }
  (void)prev;
  redraw();
}

bool playSlot(const char *name, uint32_t holdMs) {
  if (!name || !*name) return false;
  strncpy(slotName, name, sizeof(slotName) - 1);
  slotName[sizeof(slotName) - 1] = 0;
  String base = String("/slot/") + slotName;
  if (LittleFS.exists(base + ".cma")) {
    if (!cmaOpen(base + ".cma")) return false;
    src = SRC_CMA;
    state = ST_SLOT;
    view = VIEW_EYES;
    slotUntil = holdMs ? millis() + holdMs : 0;
    lastEventAt = millis();
    cmaDrawFrame(0);
    pillFor(ST_SLOT, slotName, bgColor, animIdx);
    return true;
  }
  if (LittleFS.exists(base + ".rgb")) {
    src = SRC_SLOT_IMG;
    state = ST_SLOT;
    view = VIEW_EYES;
    slotUntil = holdMs ? millis() + holdMs : 0;
    lastEventAt = millis();
    if (!loadImageIntoStage(base + ".rgb")) return false;
    scr::pushStage();
    pillFor(ST_SLOT, slotName, bgColor, animIdx);
    return true;
  }
  return false;
}

void showEvent(const String &ev, uint32_t holdMs) {
  String e = ev;
  e.trim();
  e.toLowerCase();
  if (!e.length()) return;
  // 槽位动画（击杀播报等）播放期间忽略原厂 13 种状态事件，避免被 agent 的 hook 事件立刻打断
  if (state == ST_SLOT && (int32_t)(slotUntil - millis()) > 0 &&
      (e == "idle" || e == "wake" || e == "sleep" || e == "rest" || e == "thinking" || e == "planning" ||
       e == "reading" || e == "coding" || e == "running" || e == "delegating" || e == "compacting" ||
       e == "busy" || e == "tool" || e == "waiting" || e == "notify" || e == "ask" || e == "confirm" ||
       e == "approval" || e == "done" || e == "success" || e == "error" || e == "fail")) {
    return;
  }
  if (e == "idle" || e == "wake") { setState(ST_IDLE); return; }
  if (e == "sleep" || e == "rest") { setState(ST_SLEEP); return; }
  if (e == "thinking" || e == "planning") { setState(ST_THINK); return; }
  if (e == "reading" || e == "coding" || e == "running" || e == "delegating" || e == "compacting" ||
      e == "busy" || e == "tool") { setState(ST_WORK); return; }
  if (e == "waiting" || e == "notify" || e == "ask" || e == "confirm" || e == "approval") { setState(ST_WAIT); return; }
  if (e == "done" || e == "success") { setState(ST_DONE); return; }
  if (e == "error" || e == "fail") { setState(ST_ERROR); return; }
  // 自定义槽位名
  if (playSlot(e.c_str(), holdMs)) return;
  Serial.printf("[pet] unknown event: %s\n", e.c_str());
}

void setView(uint8_t v) {
  view = v & 3;
  if (view == VIEW_TERM) {
    termLen = 0;
    termBuf[0] = 0;
    cursorOn = true;
    cursorDue = millis() + 500;
    drawTerminal(true);
  } else if (view == VIEW_CANVAS) {
    scr::fillStage(canvasBg);
    scr::pushStage();
    pillFor(state, slotName, canvasBg, animIdx);
  } else {
    frameDue = millis();
    redraw();
  }
}

void cmd(char k) {
  switch (k) {
    case 'w': setView(VIEW_EYES); break;
    case 's': setView(VIEW_SQUISH); break;
    case 'd': setView(VIEW_TERM); break;
    case 'q':
      if (view == VIEW_TERM) setView(VIEW_EYES);
      break;
    case 'a':
      // 旧固件的 logo 动画；这里用 error 动画做一个短暂的彩蛋，不改连接状态
      setState(ST_ERROR);
      break;
    default: break;
  }
}

void setBacklight(bool on) {
  backlight = on;
  scr::setBacklight(on);
}

void setSpeed(uint8_t v) {
  if (v < 1) v = 1;
  if (v > 3) v = 3;
  speed = v;
}

void setBg(uint16_t c) {
  bgColor = c;
  canvasBg = c;
  if (view == VIEW_EYES || view == VIEW_SQUISH) redraw();
  else if (view == VIEW_CANVAS) { scr::fillStage(canvasBg); scr::pushStage(); }
}

void termType(const String &chars) {
  for (size_t i = 0; i < chars.length(); i++) {
    char c = chars[i];
    if (c == 0x08) { if (termLen) termLen--; }
    else if (c == 0x0A || c == '\r') { termLen = 0; }
    else if (termLen < sizeof(termBuf) - 1) termBuf[termLen++] = c;
  }
  termBuf[termLen] = 0;
  if (view != VIEW_TERM) { setView(VIEW_TERM); }
  else drawTerminal(false);
}

void canvasOn(bool on) {
  canvasOnFlag = on;
  setView(on ? VIEW_CANVAS : VIEW_EYES);
}

void canvasClear(uint16_t bg) {
  canvasBg = bg;
  scr::fillStage(bg);
  scr::pushStage();
  pillFor(state, slotName, canvasBg, animIdx);
}

void canvasStroke(const String &pts, uint16_t pen) {
  if (view != VIEW_CANVAS) setView(VIEW_CANVAS);
  int n = pts.length();
  int idx = 0;
  int16_t px = -1, py = -1;
  int16_t minx = 32767, miny = 32767, maxx = -1, maxy = -1;
  while (idx < n) {
    int semi = pts.indexOf(';', idx);
    String pair = (semi < 0) ? pts.substring(idx) : pts.substring(idx, semi);
    idx = (semi < 0) ? n : semi + 1;
    int comma = pair.indexOf(',');
    if (comma < 0) continue;
    int x = pair.substring(0, comma).toInt();
    int y = pair.substring(comma + 1).toInt();
    if (x < 0) x = 0; if (x > 239) x = 239;
    if (y < 0) y = 0; if (y > 179) y = 179;
    if (px >= 0) {
      scr::stage().drawLine(px, py, x, y, pen);
      if (px < minx) minx = px; if (px > maxx) maxx = px;
      if (py < miny) miny = py; if (py > maxy) maxy = py;
    }
    if (x < minx) minx = x; if (x > maxx) maxx = x;
    if (y < miny) miny = y; if (y > maxy) maxy = y;
    px = x; py = y;
  }
  if (maxx >= 0) scr::pushStageRect(minx - 1, miny - 1, maxx - minx + 3, maxy - miny + 3);
  pillFor(state, slotName, canvasBg, animIdx);
}

void renderPillInto(Adafruit_GFX &gfx, int yoff) {
  uint8_t a = (state == ST_SLEEP) ? ANIM_SLEEP : (state <= ST_SLEEP ? state : animIdx);
  uint16_t bg = (state == ST_SLEEP) ? BG_SLEEP : bgColor;
  if (state == ST_SLOT) {
    const uint8_t *lb = slotLabelBits(slotName);
    scr::drawPillOffset(gfx, yoff, bg, 0xFEB4, lb, lb ? nullptr : slotName);
  }
  else scr::drawPillOffset(gfx, yoff, bg, PILL_DOT_COLOR[a], PILLTXT[a], nullptr);
}

// ───────────────────────── 心跳 ─────────────────────────

void begin() {
  Preferences p;
  p.begin("mochi", true);
  speed = p.getUChar("speed", 1);
  bgColor = p.getUShort("bg", 0xC9A0);
  backlight = p.getUChar("bl", 1) != 0;
  uint32_t c = p.getULong("bgsaved", 0);
  (void)c;
  p.end();
  LittleFS.mkdir("/base");
  LittleFS.mkdir("/slot");
  canvasBg = bgColor;
  src = SRC_ANIM;
  animIdx = ANIM_IDLE;
  state = ST_IDLE;
  frame = 0;
  frameDue = 0;
  drawAnimFrame(animIdx, 0);
  pushWithPill(state);
}

void tick() {
  uint32_t now = millis();

  // 终端光标闪烁
  if (view == VIEW_TERM) {
    if (now >= cursorDue) {
      cursorOn = !cursorOn;
      cursorDue = now + 500;
      drawTerminal(false);
    }
    return;
  }

  // 自定义槽位动画
  if (src == SRC_CMA && state == ST_SLOT) {
    if (now >= frameDue) {
      cma.curFrame = (cma.curFrame + 1) % cma.frame_n;
      uint16_t dur = cma.dur[cma.curFrame];
      if (!dur) dur = 100;
      frameDue = now + (uint32_t)dur * SPEED_NUM[speed] / SPEED_DEN[speed];
      cmaDrawFrame(cma.curFrame);
      pillFor(ST_SLOT, slotName, bgColor, animIdx);
    }
  } else if (src == SRC_ANIM && (view == VIEW_EYES || view == VIEW_SQUISH)) {
    if (now >= frameDue) {
      const AnimDef &a = ANIMS[animIdx];
      frame = (frame + 1) % a.frame_n;
      uint32_t dur = (uint32_t)a.frame_dur10[frame] * 10;
      if (!dur) dur = 100;
      frameDue = now + dur * SPEED_NUM[speed] / SPEED_DEN[speed];
      drawAnimFrame(animIdx, frame);
      if (view == VIEW_SQUISH) squishEyes();
      scr::pushStage();
    }
  }

  // 超时
  if (state == ST_DONE && now - doneAt > 5000) setState(ST_IDLE);
  else if ((state == ST_THINK || state == ST_WORK) && now - lastEventAt > 120000) setState(ST_IDLE);
  if (state == ST_SLOT && slotUntil && (int32_t)(now - slotUntil) >= 0) {
    cmaClose();
    setState(ST_IDLE);
  }
}

}  // namespace pet
