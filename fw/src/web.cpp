#include "web.h"
#include "config.h"
#include "display.h"
#include "pet.h"
#include "assets.h"
#include "web_pages.h"
#include "net.h"

#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <LittleFS.h>
#include <Preferences.h>

static WebServer server(80);

bool g_busy = false;
static bool s_restartSoon = false;
static uint32_t s_restartAt = 0;

bool webBusy() { return g_busy; }

// ───────────────────────── 工具 ─────────────────────────

static String jsonEsc(const String &in) {
  String o;
  o.reserve(in.length() + 8);
  for (size_t i = 0; i < in.length(); i++) {
    char c = in[i];
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if ((uint8_t)c < 0x20) { o += ' '; }
    else o += c;
  }
  return o;
}

static String urlDecode(const String &s) {
  String o;
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '%' && i + 2 < s.length()) {
      char h[3] = {s[i + 1], s[i + 2], 0};
      o += (char)strtol(h, nullptr, 16);
      i += 2;
    } else if (c == '+') {
      o += ' ';
    } else {
      o += c;
    }
  }
  return o;
}

static String sanitizeName(const String &in) {
  String o;
  for (size_t i = 0; i < in.length() && o.length() < 23; i++) {
    char c = in[i];
    if (isalnum((unsigned char)c) || c == '-' || c == '_') o += (char)tolower((unsigned char)c);
  }
  return o;
}

static bool parseBool(const String &v) {
  if (v == "1" || v.equalsIgnoreCase("true") || v == "on" || v == "yes") return true;
  return false;
}

static uint16_t argColor(const char *name, uint16_t fb) {
  String v = server.arg(name);
  if (!v.length()) return fb;
  return scr::parseColor(v, fb);
}

// ───────────────────────── /state ─────────────────────────

static void handleState() {
  String ssid = "";
  Preferences p;
  p.begin("mochi", true);
  ssid = p.getString("ssid", "");
  p.end();
  bool sta = (WiFi.getMode() == WIFI_STA) && (WiFi.status() == WL_CONNECTED);
  String j = "{";
  j += "\"ok\":1";
  j += ",\"view\":" + String(pet::view);
  j += ",\"busy\":" + String(g_busy ? "true" : "false");
  j += ",\"term\":" + String(pet::termOpen() ? "true" : "false");
  j += ",\"bl\":" + String(pet::backlight ? "true" : "false");
  j += ",\"speed\":" + String(pet::speed);
  j += ",\"sta\":" + String(sta ? "true" : "false");
  j += ",\"ssid\":\"" + jsonEsc(ssid) + "\"";
  j += ",\"ip\":\"" + WiFi.localIP().toString() + "\"";
  j += ",\"rssi\":" + String(sta ? WiFi.RSSI() : 0);
  j += ",\"fw\":\"" FW_VERSION "\"";
  j += ",\"name\":\"" FW_NAME "\"";
  j += ",\"anim\":\"" + String(pet::stateName(pet::state)) + "\"";
  j += ",\"slots\":" + String(pet::slotCount());
  j += ",\"bg\":\"" + String(pet::bgColor, HEX) + "\"";
  j += ",\"rot\":" + String(scr::getRotation());
  j += ",\"inv\":" + String(scr::getInvert() ? "true" : "false");
  j += ",\"heap\":" + String((uint32_t)ESP.getFreeHeap());
  j += ",\"uptime\":" + String(millis() / 1000);
  j += "}";
  server.send(200, "application/json", j);
}

// ───────────────────────── /images ─────────────────────────

static void handleImages() {
  String j = "{\"ok\":1,\"custom\":{";
  for (int i = 0; i < 7; i++) {
    if (i) j += ",";
    j += "\"" + String(i) + "\":" + String(pet::baseExists((uint8_t)i) ? "true" : "false");
  }
  j += "},\"slots\":[";
  File d = LittleFS.open("/slot");
  bool first = true;
  if (d && d.isDirectory()) {
    File e = d.openNextFile();
    while (e) {
      String nm = e.name();
      bool isRgb = nm.endsWith(".rgb");
      bool isCma = nm.endsWith(".cma");
      if (isRgb || isCma) {
        if (!first) j += ",";
        first = false;
        String base = nm.substring(nm.lastIndexOf('/') + 1);
        base = base.substring(0, base.lastIndexOf('.'));
        j += "{\"name\":\"" + jsonEsc(base) + "\",\"type\":\"" + (isCma ? "anim" : "image") + "\",\"size\":" + String((uint32_t)e.size()) + "}";
      }
      e = d.openNextFile();
    }
  }
  j += "]}";
  server.send(200, "application/json", j);
}

// ───────────────────────── 上传（multipart 流式） ─────────────────────────

static File upFile;
static String upPath;
static int upMode = 0;  // 1=底图(base), 2=槽位图, 3=槽位动画
static String upName;

static void uploadStart() {
  upFile = LittleFS.open(upPath, "w");
}

static void uploadWrite() {
  HTTPUpload &up = server.upload();
  if (upFile && up.buf && up.currentSize) upFile.write(up.buf, up.currentSize);
}

static void uploadEnd() {
  if (upFile) upFile.close();
}

static void handleImageUploadDone() {
  g_busy = false;
  if (!upPath.length()) { server.send(400, "application/json", "{\"ok\":0,\"error\":\"bad request\"}"); return; }
  File f = LittleFS.open(upPath, "r");
  bool ok = f && f.size() == ANIM_STAGE_W * ANIM_STAGE_H * 2;
  if (ok) {
    String fn = upPath.substring(upPath.lastIndexOf('/') + 1);
    String st = fn.substring(0, fn.lastIndexOf('.'));
    server.send(200, "application/json", "{\"ok\":1,\"state\":" + st + ",\"size\":" + String((uint32_t)f.size()) + "}");
  } else {
    if (f) f.close();
    LittleFS.remove(upPath);
    server.send(500, "application/json", "{\"ok\":0,\"error\":\"size must be 86400\"}");
    upPath = "";
    return;
  }
  f.close();
  upPath = "";
}

static void handleImageUpload() {
  HTTPUpload &up = server.upload();
  if (up.status == UPLOAD_FILE_START) {
    g_busy = true;
    String st = server.arg("state");
    String fn = up.filename;
    if (!st.length() && fn.length()) {
      int dot = fn.lastIndexOf('.');
      st = dot > 0 ? fn.substring(0, dot) : fn;
    }
    int n = st.toInt();
    if (n < 0 || n > 6) n = 0;
    upPath = String("/base/") + n + ".rgb";
    LittleFS.mkdir("/base");
    uploadStart();
  } else if (up.status == UPLOAD_FILE_WRITE) {
    uploadWrite();
  } else if (up.status == UPLOAD_FILE_END) {
    uploadEnd();
  }
}

static void handleSlotUploadDone() {
  g_busy = false;
  if (!upPath.length() || !upName.length()) { server.send(400, "application/json", "{\"ok\":0,\"error\":\"name required\"}"); return; }
  File f = LittleFS.open(upPath, "r");
  bool ok = false;
  String type = "image";
  if (f) {
    uint32_t sz = f.size();
    if (upMode == 3) {
      char m[4] = {0};
      f.read((uint8_t *)m, 4);
      ok = (sz > 16 && memcmp(m, "CMA1", 4) == 0);
      type = "anim";
    } else {
      ok = (sz == ANIM_STAGE_W * ANIM_STAGE_H * 2);
    }
    f.close();
  }
  if (!ok) {
    LittleFS.remove(upPath);
    server.send(500, "application/json", "{\"ok\":0,\"error\":\"invalid file\"}");
    upPath = "";
    return;
  }
  // 同名另一种格式删掉，避免二义
  if (upMode == 3) LittleFS.remove("/slot/" + upName + ".rgb");
  else LittleFS.remove("/slot/" + upName + ".cma");
  server.send(200, "application/json", "{\"ok\":1,\"name\":\"" + jsonEsc(upName) + "\",\"type\":\"" + type + "\"}");
  upPath = "";
  upName = "";
}

static void handleSlotUpload() {
  HTTPUpload &up = server.upload();
  if (up.status == UPLOAD_FILE_START) {
    g_busy = true;
    upName = sanitizeName(urlDecode(server.arg("name")));
    if (!upName.length()) { upPath = ""; return; }
    String fn = up.filename;
    bool cma = fn.endsWith(".cma") || up.name.endsWith(".cma");
    upMode = cma ? 3 : 2;
    LittleFS.mkdir("/slot");
    upPath = "/slot/" + upName + (cma ? ".cma" : ".rgb");
    File old = LittleFS.open(upPath, "r");
    if (old) { old.close(); LittleFS.remove(upPath); }
    uploadStart();
  } else if (up.status == UPLOAD_FILE_WRITE) {
    if (upPath.length()) uploadWrite();
  } else if (up.status == UPLOAD_FILE_END) {
    uploadEnd();
  }
}

// ───────────────────────── 截图（BMP 流式） ─────────────────────────

static void handleShot() {
  const int W = LCD_W, H = LCD_H;
  GFXcanvas16 *pc = new GFXcanvas16(W, H - ANIM_STAGE_H);
  if (!pc || !pc->getBuffer()) {
    if (pc) delete pc;
    server.send(503, "application/json", "{\"ok\":0,\"error\":\"no mem\"}");
    return;
  }
  pet::renderPillInto(*pc, ANIM_STAGE_H);

  const uint32_t rowBytes = W * 3;
  const uint32_t imgBytes = rowBytes * H;
  uint8_t hdr[54];
  memset(hdr, 0, sizeof(hdr));
  hdr[0] = 'B'; hdr[1] = 'M';
  uint32_t fsize = 54u + imgBytes;
  hdr[2] = (uint8_t)(fsize & 0xFF); hdr[3] = (uint8_t)((fsize >> 8) & 0xFF);
  hdr[4] = (uint8_t)((fsize >> 16) & 0xFF); hdr[5] = (uint8_t)((fsize >> 24) & 0xFF);
  hdr[10] = 54;
  hdr[14] = 40;
  hdr[18] = (uint8_t)(W & 0xFF); hdr[19] = (uint8_t)((W >> 8) & 0xFF);
  hdr[22] = (uint8_t)(H & 0xFF); hdr[23] = (uint8_t)((H >> 8) & 0xFF);
  hdr[26] = 1;
  hdr[28] = 24;
  hdr[34] = (uint8_t)(imgBytes & 0xFF); hdr[35] = (uint8_t)((imgBytes >> 8) & 0xFF);
  hdr[36] = (uint8_t)((imgBytes >> 16) & 0xFF); hdr[37] = (uint8_t)((imgBytes >> 24) & 0xFF);
  hdr[38] = (uint8_t)(2835 & 0xFF); hdr[39] = (uint8_t)((2835 >> 8) & 0xFF);
  hdr[42] = (uint8_t)(2835 & 0xFF); hdr[43] = (uint8_t)((2835 >> 8) & 0xFF);

  server.setContentLength(54 + imgBytes);
  server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  server.send(200, "image/bmp", "");
  server.sendContent((const char *)hdr, 54);

  uint8_t row[LCD_W * 3];
  const uint16_t *fb = scr::stage().getBuffer();
  const uint16_t *pb = pc->getBuffer();
  const int pillRows = H - ANIM_STAGE_H;
  for (int y = H - 1; y >= 0; y--) {
    const uint16_t *s = (y >= ANIM_STAGE_H) ? (pb + (y - ANIM_STAGE_H) * W) : (fb + y * ANIM_STAGE_W);
    for (int x = 0; x < W; x++) {
      uint16_t c = s[x];
      uint8_t r = (c >> 11) << 3, g = ((c >> 5) & 0x3F) << 2, b = (c & 0x1F) << 3;
      row[x * 3 + 0] = b;
      row[x * 3 + 1] = g;
      row[x * 3 + 2] = r;
    }
    server.sendContent((const char *)row, rowBytes);
  }
  (void)pillRows;
  delete pc;
}

// ───────────────────────── 端点注册 ─────────────────────────

void webBegin() {
  // 页面
  server.on("/", HTTP_GET, []() {
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    server.send_P(200, "text/html", PAGE_CONTROL);
  });
  server.on("/index.html", HTTP_GET, []() {
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    server.send_P(200, "text/html", PAGE_CONTROL);
  });
  server.on("/wifi", HTTP_GET, []() {
    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    server.send_P(200, "text/html", PAGE_WIFI);
  });

  server.on("/state", HTTP_GET, handleState);
  server.on("/health", HTTP_GET, []() { server.send(200, "application/json", "{\"ok\":1,\"fw\":\"" FW_VERSION "\"}"); });
  server.on("/images", HTTP_GET, handleImages);
  server.on("/anim/list", HTTP_GET, []() {
    server.send(200, "application/json",
                "{\"ok\":1,\"builtin\":[\"idle\",\"thinking\",\"working\",\"waiting\",\"done\",\"error\",\"sleep\"]}");
  });

  server.on("/event", HTTP_GET, []() {
    String s = server.arg("s");
    uint32_t hold = server.hasArg("h") ? server.arg("h").toInt() : 0;
    if (s.length()) pet::showEvent(s, hold);
    server.send(200, "application/json", "{\"ok\":1,\"event\":\"" + jsonEsc(s) + "\"}");
  });

  server.on("/cmd", HTTP_GET, []() {
    String k = server.arg("k");
    if (k.length()) pet::cmd(k[0]);
    server.send(200, "application/json", "{\"ok\":1,\"view\":" + String(pet::view) + "}");
  });

  server.on("/char", HTTP_GET, []() {
    String c = urlDecode(server.arg("c"));
    pet::termType(c);
    server.send(200, "application/json", "{\"ok\":1}");
  });

  server.on("/speed", HTTP_GET, []() {
    int v = server.arg("v").toInt();
    if (v) pet::setSpeed((uint8_t)v);
    server.send(200, "application/json", "{\"ok\":1,\"speed\":" + String(pet::speed) + "}");
  });

  server.on("/backlight", HTTP_GET, []() {
    String v = server.arg("on");
    if (v.length()) pet::setBacklight(parseBool(v));
    server.send(200, "application/json", "{\"ok\":1,\"bl\":" + String(pet::backlight ? "true" : "false") + "}");
  });

  server.on("/redraw", HTTP_GET, []() {
    uint16_t bg = argColor("bg", pet::bgColor);
    pet::setBg(bg);
    pet::setView(VIEW_EYES);
    server.send(200, "application/json", "{\"ok\":1,\"bg\":\"" + String(bg, HEX) + "\"}");
  });

  server.on("/canvas", HTTP_GET, []() {
    String v = server.arg("on");
    pet::canvasOn(parseBool(v));
    server.send(200, "application/json", "{\"ok\":1,\"view\":" + String(pet::view) + "}");
  });

  server.on("/draw/clear", HTTP_GET, []() {
    uint16_t bg = argColor("bg", 0x0000);
    pet::canvasClear(bg);
    server.send(200, "application/json", "{\"ok\":1}");
  });

  server.on("/draw/stroke", HTTP_GET, []() {
    uint16_t pen = argColor("pen", 0xFFFF);
    String pts = server.arg("pts");
    pet::canvasStroke(pts, pen);
    server.send(200, "application/json", "{\"ok\":1,\"pts\":" + String(pts.length()) + "}");
  });

  server.on("/image/upload", HTTP_POST, handleImageUploadDone, handleImageUpload);
  server.on("/image/reset", HTTP_GET, []() {
    String st = server.arg("state");
    int n = st.toInt();
    if (n < 0 || n > 6) n = 0;
    LittleFS.remove(String("/base/") + n + ".rgb");
    server.send(200, "application/json", "{\"ok\":1,\"state\":" + String(n) + "}");
  });

  // 自定义槽位
  server.on("/slot/list", HTTP_GET, handleImages);
  server.on("/slot/upload", HTTP_POST, handleSlotUploadDone, handleSlotUpload);
  server.on("/slot/delete", HTTP_GET, []() {
    String nm = sanitizeName(urlDecode(server.arg("name")));
    bool ok = false;
    if (nm.length()) {
      if (LittleFS.remove("/slot/" + nm + ".rgb")) ok = true;
      if (LittleFS.remove("/slot/" + nm + ".cma")) ok = true;
    }
    server.send(200, "application/json", "{\"ok\":" + String(ok ? 1 : 0) + "}");
  });

  server.on("/screenshot.bmp", HTTP_GET, handleShot);

  server.on("/panel", HTTP_GET, []() {
    uint8_t rot = server.hasArg("rot") ? (uint8_t)server.arg("rot").toInt() : scr::getRotation();
    bool inv = server.hasArg("inv") ? parseBool(server.arg("inv")) : scr::getInvert();
    scr::setPanel(rot, inv);
    server.send(200, "application/json", "{\"ok\":1,\"rot\":" + String(rot) + ",\"inv\":" + String(inv ? "true" : "false") + "}");
  });

  // ── 网络诊断（0.1.3）：直接看设备侧能不能上外网 / 有没有被 portal 拦 ──
  server.on("/net/get", HTTP_GET, []() {
    String u = server.arg("url");
    if (!u.length()) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"url required\"}"); return; }
    bool follow = parseBool(server.arg("follow"));
    net::GetResult r = net::get(u, 8000, follow);
    String j = "{\"ok\":";
    j += r.ok ? "true" : "false";
    j += ",\"status\":" + String(r.status);
    j += ",\"len\":" + String((long)r.len);
    j += ",\"location\":\"" + jsonEsc(r.location) + "\"";
    j += ",\"server\":\"" + jsonEsc(r.server) + "\"";
    j += ",\"body\":\"" + jsonEsc(r.snippet) + "\"";
    j += ",\"error\":\"" + jsonEsc(r.error) + "\"";
    j += ",\"ssid\":\"" + jsonEsc(WiFi.SSID()) + "\",\"ip\":\"" + WiFi.localIP().toString() + "\"";
    j += "}";
    server.send(200, "application/json", j);
  });

  server.on("/wifi/status", HTTP_GET, []() {
    String j = "{\"ok\":1,\"status\":" + String((int)WiFi.status());
    j += ",\"ssid\":\"" + jsonEsc(WiFi.SSID()) + "\"";
    j += ",\"ip\":\"" + WiFi.localIP().toString() + "\"";
    j += ",\"gw\":\"" + WiFi.gatewayIP().toString() + "\"";
    j += ",\"rssi\":" + String(WiFi.RSSI());
    j += ",\"saved_ssid\":\"" + jsonEsc(net::savedSsid()) + "\"}";
    server.send(200, "application/json", j);
  });

  // 试连某个网络但不保存（成功就留在该网络；失败回到原网络），用于试探校园网
  server.on("/wifi/try", HTTP_GET, []() {
    String ssid = urlDecode(server.arg("ssid"));
    String pass = urlDecode(server.arg("pass"));
    if (!ssid.length()) { server.send(400, "application/json", "{\"ok\":false,\"error\":\"ssid required\"}"); return; }
    g_busy = true;
    bool ok = net::connect(ssid, pass, 20000);
    g_busy = false;
    server.send(200, "application/json",
                "{\"ok\":" + String(ok ? "true" : "false") + ",\"ssid\":\"" + jsonEsc(ssid) +
                    "\",\"ip\":\"" + WiFi.localIP().toString() + "\",\"rssi\":" + String(WiFi.RSSI()) +
                    ",\"status\":" + String((int)WiFi.status()) + "}");
  });

  // WiFi
  server.on("/wifi/scan", HTTP_GET, []() {
    g_busy = true;
    int n = WiFi.scanNetworks();
    String j = "[";
    for (int i = 0; i < n; i++) {
      if (i) j += ",";
      j += "{\"ssid\":\"" + jsonEsc(WiFi.SSID(i)) + "\",\"rssi\":" + String(WiFi.RSSI(i)) + "}";
    }
    j += "]";
    WiFi.scanDelete();
    g_busy = false;
    server.send(200, "application/json", j);
  });

  server.on("/wifi/save", HTTP_GET, []() {
    String ssid = urlDecode(server.arg("ssid"));
    String pass = urlDecode(server.arg("pass"));
    if (ssid.length()) {
      Preferences p;
      p.begin("mochi", false);
      p.putString("ssid", ssid);
      p.putString("pass", pass);
      p.end();
    }
    server.send(200, "application/json", "{\"ok\":1,\"msg\":\"saved, rebooting\"}");
    s_restartSoon = true;
    s_restartAt = millis() + 600;
  });

  server.on("/wifi/forget", HTTP_GET, []() {
    Preferences p;
    p.begin("mochi", false);
    p.remove("ssid");
    p.remove("pass");
    p.end();
    server.send(200, "application/json", "{\"ok\":1,\"msg\":\"forgotten, rebooting to AP\"}");
    s_restartSoon = true;
    s_restartAt = millis() + 600;
  });

  server.onNotFound([]() { server.send(404, "application/json", "{\"ok\":false,\"error\":\"not found\"}"); });

  server.begin();
  Serial.printf("[web] http server on :80\n");
}

void webLoop() {
  server.handleClient();
  if (s_restartSoon && (int32_t)(millis() - s_restartAt) >= 0) {
    Serial.println("[web] restarting...");
    delay(50);
    ESP.restart();
  }
}
