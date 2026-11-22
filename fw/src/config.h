#pragma once
#include <Arduino.h>

// ---- 硬件引脚（来自官方"散件安装"文档，最新硬件 GPIO3–8）----
#define PIN_LCD_MOSI 3
#define PIN_LCD_SCK  4
#define PIN_LCD_DC   5
#define PIN_LCD_RST  6
#define PIN_LCD_BL   7
#define PIN_LCD_CS   8

#define LCD_W 240
#define LCD_H 240

// 舞台（表情动画 / 自定义图片）区域高度；下方 60px 留给状态牌
#define STAGE_H 180

// ---- WiFi ----
// 本仓库不包含任何真实 WiFi 凭据。
// 想内置"开机首选网络"，把凭据放进 src/config_secrets.h（已在 .gitignore 里）：
//
//   #pragma once
//   #include "config.h"
//   static const WifiCred DEFAULT_NETS[] = {
//       {"MyHomeWiFi", "my-password"},
//       {"NEFU-WIFI", ""},           // 开放网络：密码留空
//   };
//
// 不建 config_secrets.h 也完全可用：首次配网用下面任一方式
//   1) 串口控制台：save <ssid> [pass]（115200 8N1，命令后自动重启）
//   2) 设备网页：http://clawd-mochi.local/wifi
//   3) 没网时设备会开热点 Clawd-Mochi / clawdmochi，连上去配网
struct WifiCred { const char *ssid; const char *pass; };

#if __has_include("config_secrets.h")
#include "config_secrets.h"
#else
// 占位：留空即可（编译出的固件开机后进 AP 配网模式）
static const WifiCred DEFAULT_NETS[1] = {{"", ""}};
#endif

#define MDNS_HOST "clawd-mochi"
#define FW_NAME "clawd-mochi-custom"
#define FW_VERSION "0.1.4"
