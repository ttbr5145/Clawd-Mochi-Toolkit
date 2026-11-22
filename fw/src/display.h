// 显示层：ST7789 240x240 面板 + 240x180 舞台帧缓冲（内置动画/自定义图都画在舞台）
// 底部 60px 状态牌直接画到面板（不进帧缓冲，省 28.8KB 内存）
#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include "config.h"

namespace scr {
extern GFXcanvas16 *fb;                 // 240x180 舞台
inline GFXcanvas16 &stage() { return *fb; }

bool begin();
void setBacklight(bool on);
void setPanel(uint8_t rotation, bool invert);   // 运行时调旋转/反色并持久化
uint8_t getRotation();
bool getInvert();

void pushStage();                                   // 整幅舞台推到面板
void pushStageRect(int16_t x, int16_t y, int16_t w, int16_t h);
void fillStage(uint16_t color);

// 状态牌：bg = 舞台底色(牌区外)，dot = 状态点颜色，txtBits = 60x22 1bit 位图(可为 nullptr)，
// text = ASCII 文本(位图为空时使用)
void drawPill(Adafruit_GFX &gfx, uint16_t bg, uint16_t dot, const uint8_t *txtBits, const char *text);
// 同上，但把状态牌画到 yoff 偏移的画布上（截图时用 60 行小画布）
void drawPillOffset(Adafruit_GFX &gfx, int yoff, uint16_t bg, uint16_t dot, const uint8_t *txtBits, const char *text);
void showPill(uint16_t bg, uint16_t dot, const uint8_t *txtBits, const char *text);

uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b);
uint16_t parseColor(const String &hex, uint16_t fallback = 0xC9A0);
}
