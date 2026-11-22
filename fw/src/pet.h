// 宠物状态机 + 渲染（内置动画 / 自定义底图 / 自定义槽位动画 / 终端 / 画布）
#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>

enum PetState : uint8_t {
  ST_IDLE = 0, ST_THINK = 1, ST_WORK = 2, ST_WAIT = 3,
  ST_DONE = 4, ST_ERROR = 5, ST_SLEEP = 6, ST_SLOT = 7
};

enum PetView : uint8_t { VIEW_EYES = 0, VIEW_SQUISH = 1, VIEW_TERM = 2, VIEW_CANVAS = 3 };

namespace pet {
extern uint8_t state;
extern uint8_t view;
extern uint8_t speed;
extern uint16_t bgColor;
extern bool backlight;

void begin();
void tick();

void showEvent(const String &ev, uint32_t holdMs = 0);   // 13 官方事件名 / done / 或自定义槽名
bool playSlot(const char *name, uint32_t holdMs = 0);
void setState(uint8_t st);
void setView(uint8_t v);
void cmd(char k);                                        // w / s / d / q / a
void redraw();

void setBacklight(bool on);
void setSpeed(uint8_t v);
void setBg(uint16_t c);
void termType(const String &chars);
void canvasOn(bool on);
void canvasClear(uint16_t bg);
void canvasStroke(const String &pts, uint16_t pen);

bool baseExists(uint8_t st);
bool slotExists(const char *name);
uint32_t slotCount();

const char *stateName(uint8_t st);
const __FlashStringHelper *stateLabel(uint8_t st);

// 截图用：把当前状态牌画进外部位图（yoff 通常 180）
void renderPillInto(Adafruit_GFX &gfx, int yoff);
inline bool termOpen() { return view == VIEW_TERM; }
inline bool canvasOpen() { return view == VIEW_CANVAS; }
}  // namespace pet
