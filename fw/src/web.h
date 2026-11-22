// HTTP 服务：兼容原厂控制中心与设备控制器页 + 自定义槽位扩展
#pragma once
#include <Arduino.h>

void webBegin();      // WiFi 连上（或进了配网 AP）后调用
void webLoop();
bool webBusy();
