#include <Arduino.h>
#include "config.h"
#include "display.h"
#include "pet.h"
#include "web.h"
#include "net.h"

#include <LittleFS.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>

// ───────────── 串口控制台（USB 插着时可用；网络挂了也能救回来） ─────────────
static String s_cmdBuf;
static bool s_restartPending = false;
static uint32_t s_restartAt = 0;

static void printIp() {
  Serial.printf("[net] status=%d ssid=%s ip=%s rssi=%d gw=%s\n", (int)WiFi.status(), WiFi.SSID().c_str(),
                WiFi.localIP().toString().c_str(), WiFi.RSSI(), WiFi.gatewayIP().toString().c_str());
}

static void handleCommand(String line) {
  line.trim();
  if (!line.length()) return;

  // ── 官方 USB CDC 协议（Windows 控制中心「USB 有线」模式发的就是这些行，115200）──
  if (line.startsWith("EVENT ")) {  // EVENT coding / EVENT idle / EVENT <槽位名>
    pet::showEvent(line.substring(6));
    Serial.println("[usb] OK");
    return;
  }
  if (line == "PING") {
    Serial.println("PONG");
    return;
  }
  if (line == "STATE") {
    Serial.printf("[usb] STATE state=%s view=%d bg=%04x speed=%d bl=%d slots=%u ip=%s\n", pet::stateName(pet::state),
                  (int)pet::view, (unsigned)pet::bgColor, (int)pet::speed, (int)(pet::backlight ? 1 : 0),
                  (unsigned)pet::slotCount(), WiFi.localIP().toString().c_str());
    return;
  }
  if (line.startsWith("VIEW ")) {  // VIEW idle / VIEW sleep（休息中）
    String v = line.substring(5);
    v.toLowerCase();
    if (v == "sleep")
      pet::setState(ST_SLEEP);
    else
      pet::setState(ST_IDLE);
    Serial.println("[usb] OK");
    return;
  }
  if (line.startsWith("BACKLIGHT ")) {
    pet::setBacklight(line.substring(10).toInt() != 0);
    Serial.println("[usb] OK");
    return;
  }
  if (line.startsWith("SPEED ")) {
    pet::setSpeed((uint8_t)line.substring(6).toInt());
    Serial.println("[usb] OK");
    return;
  }
  if (line.startsWith("BG ")) {
    pet::setBg(scr::parseColor(line.substring(3)));
    Serial.println("[usb] OK");
    return;
  }
  if (line.startsWith("HELP")) {
    Serial.println("[usb] EVENT <name> | STATE | VIEW idle|sleep | BACKLIGHT 0|1 | SPEED 1|2|3 | BG RRGGBB | PING");
    return;
  }

  int sp1 = line.indexOf(' ');
  String cmd = (sp1 < 0) ? line : line.substring(0, sp1);
  String rest = (sp1 < 0) ? "" : line.substring(sp1 + 1);
  rest.trim();
  cmd.toLowerCase();

  if (cmd == "help") {
    Serial.println("[cmd] help | ip | scan | state | net <url> | wifi <ssid> [pass] | save <ssid> [pass] | forget | reboot");
  } else if (cmd == "ip") {
    printIp();
  } else if (cmd == "state") {
    Serial.printf("[cmd] anim=%s view=%d bg=%04x speed=%d slots=%u heap=%u\n", pet::stateName(pet::state),
                  (int)pet::view, (unsigned)pet::bgColor, (int)pet::speed, (unsigned)pet::slotCount(),
                  (unsigned)ESP.getFreeHeap());
  } else if (cmd == "scan") {
    int n = WiFi.scanNetworks();
    Serial.printf("[cmd] %d networks\n", n);
    for (int i = 0; i < n && i < 20; i++)
      Serial.printf("  %2d %-24s rssi=%-4d ch=%-3d enc=%d\n", i, WiFi.SSID(i).c_str(), WiFi.RSSI(i),
                    WiFi.channel(i), (int)WiFi.encryptionType(i));
    WiFi.scanDelete();
  } else if (cmd == "net") {
    if (!rest.length()) { Serial.println("[cmd] usage: net <url>"); return; }
    net::GetResult r = net::get(rest, 8000, false);
    Serial.printf("[net] ok=%d status=%d len=%ld loc=%s server=%s err=%s\n", (int)r.ok, r.status, (long)r.len,
                  r.location.c_str(), r.server.c_str(), r.error.c_str());
    if (r.snippet.length()) Serial.printf("[net] body: %s\n", r.snippet.c_str());
  } else if (cmd == "wifi") {
    int sp = rest.indexOf(' ');
    String ssid = (sp < 0) ? rest : rest.substring(0, sp);
    String pass = (sp < 0) ? "" : rest.substring(sp + 1);
    Serial.printf("[cmd] connecting to %s ...\n", ssid.c_str());
    if (net::connect(ssid, pass, 20000)) printIp();
    else Serial.println("[cmd] connect failed");
  } else if (cmd == "save") {
    int sp = rest.indexOf(' ');
    String ssid = (sp < 0) ? rest : rest.substring(0, sp);
    String pass = (sp < 0) ? "" : rest.substring(sp + 1);
    if (!ssid.length()) { Serial.println("[cmd] usage: save <ssid> [pass]"); return; }
    net::saveCreds(ssid, pass);
    Serial.printf("[cmd] saved %s, rebooting\n", ssid.c_str());
    s_restartPending = true;
    s_restartAt = millis() + 800;
  } else if (cmd == "forget") {
    Preferences p;
    p.begin("mochi", false);
    p.remove("ssid");
    p.remove("pass");
    p.end();
    Serial.println("[cmd] forgotten, rebooting");
    s_restartPending = true;
    s_restartAt = millis() + 800;
  } else if (cmd == "reboot") {
    Serial.println("[cmd] rebooting");
    s_restartPending = true;
    s_restartAt = millis() + 300;
  } else {
    Serial.printf("[cmd] unknown: %s\n", cmd.c_str());
  }
}

static void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      String line = s_cmdBuf;
      s_cmdBuf = "";
      handleCommand(line);
    } else if (s_cmdBuf.length() < 300) {
      s_cmdBuf += c;
    }
  }
}

static void startAP() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP("Clawd-Mochi", "clawdmochi");
  Serial.printf("[wifi] AP mode, ip=%s\n", WiFi.softAPIP().toString().c_str());
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.printf("[boot] %s %s\n", FW_NAME, FW_VERSION);

  if (!LittleFS.begin(true)) {
    Serial.println("[fs] LittleFS mount failed");
  } else {
    Serial.printf("[fs] used=%u total=%u\n", (unsigned)LittleFS.usedBytes(), (unsigned)LittleFS.totalBytes());
  }
  LittleFS.mkdir("/base");
  LittleFS.mkdir("/slot");

  if (!scr::begin()) {
    Serial.println("[disp] init failed");
  }
  pet::begin();

  net::setPollHook(pollSerial);
  net::loadCreds();
  if (net::connectAny(15000)) {
    printIp();
  } else {
    Serial.println("[net] no known network reachable");
    startAP();
  }

  if (MDNS.begin(MDNS_HOST)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("[mdns] http://%s.local/\n", MDNS_HOST);
  } else {
    Serial.println("[mdns] begin failed");
  }

  webBegin();
  pet::setState(ST_IDLE);
  Serial.println("[cmd] ready - type 'help'");
}

void loop() {
  webLoop();
  pet::tick();
  pollSerial();
  if (s_restartPending && (int32_t)(millis() - s_restartAt) >= 0) {
    Serial.println("[cmd] restarting...");
    delay(50);
    ESP.restart();
  }
  delay(1);
}
