#pragma once
#include <Arduino.h>

namespace net {
// 连接等待期间的回调（用于在阻塞等待时继续处理串口，保证 USB 握手能应答）
void setPollHook(void (*fn)());

struct GetResult {
  bool ok = false;          // TCP 层成功（有响应）
  int status = -1;          // HTTP 状态码
  int32_t len = -1;         // Content-Length（-1 未知）
  String location;          // Location 头（看 portal 跳转）
  String server;            // Server 头
  String snippet;           // 正文前 ~180 字节（去换行）
  String error;             // 失败原因
};

// 从 Preferences("mochi") 读已保存的 ssid/pass（可能为空）
void loadCreds();
bool hasCreds();
String savedSsid();
String savedPass();

// 连接指定网络；pass 为空 => 开放网络（无密码）
bool connect(const String &ssid, const String &pass, uint32_t timeoutMs = 20000);

// 依次尝试：已保存的网络 → 内置 DEFAULT_NETS
bool connectAny(uint32_t perTryMs = 15000);

// 保存到 NVS（下次启动用），返回是否写入成功
void saveCreds(const String &ssid, const String &pass);

// HTTP GET，不自动跟随跳转（要看 portal 的 302/302 Location）
GetResult get(const String &url, uint32_t timeoutMs = 8000, bool follow = false);

}  // namespace net
