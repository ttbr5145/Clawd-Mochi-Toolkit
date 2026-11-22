#include "display.h"
#include "assets.h"
#include <SPI.h>
#include <Preferences.h>

namespace scr {

GFXcanvas16 *fb = nullptr;
static Adafruit_ST7789 *tft = nullptr;
static uint8_t s_rot = 2;
static bool s_inv = true;  // 原厂面板是反显的（不反会得到橙色->浅蓝、幽灵白边）
static bool s_bl = true;

bool begin() {
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, HIGH);

  // 面板参数（旋转/反显）持久化在 NVS，便于远程修正。
  // cfgv: 配置版本。v<2 的旧 NVS（当初测试写入了 inv=0）一律重置为反显，
  // 因为原厂面板是反显的：不反会得到橙色->浅蓝、黑边->白边（"幽灵"效果）。
  {
    Preferences pp;
    pp.begin("mochi", false);
    uint8_t cfgv = pp.getUChar("cfgv", 0);
    s_rot = pp.getUChar("rot", 2) & 3;
    if (cfgv >= 2) {
      s_inv = pp.getBool("inv", true);
    } else {
      s_inv = true;
      pp.putUChar("inv", 1);
    }
    pp.putUChar("cfgv", 2);
    pp.end();
  }

  SPI.begin(PIN_LCD_SCK, -1, PIN_LCD_MOSI, PIN_LCD_CS);
  tft = new Adafruit_ST7789(&SPI, PIN_LCD_CS, PIN_LCD_DC, PIN_LCD_RST);
  if (!tft) return false;
  tft->init(LCD_W, LCD_H);
  tft->setRotation(s_rot);
  tft->setSPISpeed(40000000);
  tft->invertDisplay(s_inv);
  tft->fillScreen(0x0000);

  fb = new GFXcanvas16(ANIM_STAGE_W, ANIM_STAGE_H);
  if (!fb || !fb->getBuffer()) return false;
  fb->fillScreen(0xC9A0);
  pushStage();
  return true;
}

void setBacklight(bool on) {
  s_bl = on;
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_BL, on ? HIGH : LOW);
}

void setPanel(uint8_t rotation, bool invert) {
  s_rot = rotation & 3;
  s_inv = invert;
  if (!tft) return;
  tft->setRotation(s_rot);
  tft->invertDisplay(s_inv);
  tft->fillScreen(0x0000);
  pushStage();
  Preferences p;
  p.begin("mochi", false);
  p.putUChar("rot", s_rot);
  p.putUChar("inv", s_inv ? 1 : 0);
  p.putUChar("cfgv", 2);
  p.end();
}

uint8_t getRotation() { return s_rot; }
bool getInvert() { return s_inv; }

void fillStage(uint16_t color) {
  if (fb) fb->fillScreen(color);
}

void pushStage() {
  if (!tft || !fb) return;
  tft->drawRGBBitmap(0, 0, fb->getBuffer(), ANIM_STAGE_W, ANIM_STAGE_H);
}

void pushStageRect(int16_t x, int16_t y, int16_t w, int16_t h) {
  if (!tft || !fb) return;
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > ANIM_STAGE_W) w = ANIM_STAGE_W - x;
  if (y + h > ANIM_STAGE_H) h = ANIM_STAGE_H - y;
  if (w <= 0 || h <= 0) return;
  tft->startWrite();
  tft->setAddrWindow(x, y, w, h);
  tft->writePixels(fb->getBuffer() + (uint32_t)y * ANIM_STAGE_W + x, w * h);
  tft->endWrite();
}

void drawPillOffset(Adafruit_GFX &gfx, int yoff, uint16_t bg, uint16_t dot, const uint8_t *txtBits, const char *text) {
  // 牌区底色
  gfx.fillRect(0, ANIM_STAGE_H - yoff, LCD_W, LCD_H - ANIM_STAGE_H, bg);
  // 圆角牌
  gfx.fillRoundRect(PILL_X, PILL_Y - yoff, PILL_W, PILL_H, PILL_R, PILL_FILL);
  gfx.drawRoundRect(PILL_X, PILL_Y - yoff, PILL_W, PILL_H, PILL_R, PILL_BORDER);
  // 状态点
  gfx.fillRoundRect(PILL_DOT_X, PILL_DOT_Y - yoff, PILL_DOT_W, PILL_DOT_W, 3, dot);
  // 文字
  if (txtBits) {
    for (int row = 0; row < PILL_TEXT_H; row++) {
      const uint8_t *p = txtBits + row * 8;
      int x = 0;
      while (x < PILL_TEXT_W) {
        bool on = (p[x >> 3] >> (x & 7)) & 1;
        if (!on) { x++; continue; }
        int run = 1;
        while (x + run < PILL_TEXT_W && ((p[(x + run) >> 3] >> ((x + run) & 7)) & 1)) run++;
        gfx.fillRect(PILL_TEXT_X + x, PILL_TEXT_Y - yoff + row, run, 1, PILL_TEXTCOL);
        x += run;
      }
    }
  } else if (text && text[0]) {
    gfx.setTextSize(2);
    gfx.setTextColor(PILL_TEXTCOL);
    int16_t x1, y1;
    uint16_t tw, th;
    gfx.getTextBounds(text, 0, 0, &x1, &y1, &tw, &th);
    int tx = PILL_TEXT_X + (PILL_TEXT_W - (int)tw) / 2;
    int ty = PILL_TEXT_Y - yoff + (PILL_TEXT_H - (int)th) / 2;
    if (tx < PILL_X + 6) tx = PILL_X + 6;
    gfx.setCursor(tx, ty);
    gfx.print(text);
  }
}

void drawPill(Adafruit_GFX &gfx, uint16_t bg, uint16_t dot, const uint8_t *txtBits, const char *text) {
  drawPillOffset(gfx, 0, bg, dot, txtBits, text);
}

void showPill(uint16_t bg, uint16_t dot, const uint8_t *txtBits, const char *text) {
  if (!tft) return;
  drawPill(*tft, bg, dot, txtBits, text);
}

uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return ((uint16_t)(r & 0xF8) << 8) | ((uint16_t)(g & 0xFC) << 3) | (b >> 3);
}

uint16_t parseColor(const String &hex, uint16_t fallback) {
  String s = hex;
  if (s.startsWith("#")) s = s.substring(1);
  if (s.length() != 6) return fallback;
  char buf[3] = {0, 0, 0};
  buf[0] = s[0]; buf[1] = s[1];
  uint8_t r = strtol(buf, nullptr, 16);
  buf[0] = s[2]; buf[1] = s[3];
  uint8_t g = strtol(buf, nullptr, 16);
  buf[0] = s[4]; buf[1] = s[5];
  uint8_t b = strtol(buf, nullptr, 16);
  return rgb565(r, g, b);
}

}  // namespace scr
