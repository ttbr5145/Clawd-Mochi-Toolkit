#include "net.h"
#include "config.h"

#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>

namespace net {

static void (*s_pollHook)() = nullptr;
void setPollHook(void (*fn)()) { s_pollHook = fn; }

static String s_ssid;
static String s_pass;

void loadCreds() {
  Preferences p;
  p.begin("mochi", true);
  s_ssid = p.getString("ssid", "");
  s_pass = p.getString("pass", "");
  p.end();
}

bool hasCreds() { return s_ssid.length() > 0; }
String savedSsid() { return s_ssid; }
String savedPass() { return s_pass; }

bool connect(const String &ssid, const String &pass, uint32_t timeoutMs) {
  if (!ssid.length()) return false;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setHostname(MDNS_HOST);
  WiFi.disconnect(false, false);
  delay(60);
  if (pass.length())
    WiFi.begin(ssid.c_str(), pass.c_str());
  else
    WiFi.begin(ssid.c_str());  // 开放网络

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && (int32_t)(millis() - t0) < (int32_t)timeoutMs) {
    delay(150);
    if (s_pollHook) s_pollHook();
    yield();
  }
  return WiFi.status() == WL_CONNECTED;
}

bool connectAny(uint32_t perTryMs) {
  // 1) 已保存的
  if (hasCreds()) {
    Serial.printf("[net] try saved ssid=%s\n", s_ssid.c_str());
    if (connect(s_ssid, s_pass, perTryMs)) return true;
  }
  // 2) 内置清单（按顺序）
  for (size_t i = 0; i < sizeof(DEFAULT_NETS) / sizeof(DEFAULT_NETS[0]); i++) {
    const char *ssid = DEFAULT_NETS[i].ssid;
    if (!ssid || !*ssid) continue;               // 空占位：跳过
    if (hasCreds() && s_ssid == ssid) continue;  // 已试过
    Serial.printf("[net] try builtin ssid=%s\n", ssid);
    if (connect(String(ssid), String(DEFAULT_NETS[i].pass), perTryMs)) return true;
  }
  return false;
}

void saveCreds(const String &ssid, const String &pass) {
  Preferences p;
  p.begin("mochi", false);
  p.putString("ssid", ssid);
  p.putString("pass", pass);
  p.end();
  s_ssid = ssid;
  s_pass = pass;
}

GetResult get(const String &url, uint32_t timeoutMs, bool follow) {
  GetResult r;
  if (WiFi.status() != WL_CONNECTED) {
    r.error = "wifi not connected";
    return r;
  }
  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setConnectTimeout(timeoutMs);
  http.setFollowRedirects(follow ? HTTPC_STRICT_FOLLOW_REDIRECTS : HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.setUserAgent("clawd-mochi/0.1.3");
  if (!http.begin(url)) {
    r.error = "begin failed";
    return r;
  }
  int code = http.GET();
  if (code <= 0) {
    r.error = String("GET failed: ") + http.errorToString(code);
    http.end();
    return r;
  }
  r.ok = true;
  r.status = code;
  r.len = http.getSize();
  r.location = http.header("Location");
  r.server = http.header("Server");

  if (auto *st = http.getStreamPtr()) {
    String body;
    uint32_t t0 = millis();
    while (st->available() && body.length() < 260 && (int32_t)(millis() - t0) < 1500) {
      char c = (char)st->read();
      if (c == '\r') continue;
      if (c == '\n') { body += ' '; continue; }
      body += c;
    }
    r.snippet = body;
  }
  http.end();
  return r;
}

}  // namespace net
