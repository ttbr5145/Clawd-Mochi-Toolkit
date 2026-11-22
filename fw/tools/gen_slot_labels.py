import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FW = _os.path.dirname(_HERE)
_ROOT = _os.path.dirname(_FW)
"""把槽位的显示文字渲染成 60x22 1-bit 位图（与内置状态牌文字同规格），生成 fw/src/slot_labels.h。

位图格式与 assets.h 的 PILLTXT_* 一致：22 行 x 8 字节 = 176 字节，bit=(byte>>(x&7))&1。
用法：python gen_slot_labels.py
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

OUT = _os.path.join(_FW, "src", "slot_labels.h")
FONTS = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]
CW, CH = 60, 22

# 槽位名 -> 显示文字
LABELS = [
    ("kill1", "单杀"),
    ("kill2", "双杀"),
    ("kill3", "三杀"),
    ("kill4", "四杀"),
    ("kill5", "ACE"),
    ("death", "阵亡"),
    ("roundwin", "胜利"),
    ("roundlose", "失败"),
]


def load_font(size):
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render(text):
    """白字黑底，居中，返回 1-bit 位图字节。"""
    im = Image.new("L", (CW, CH), 0)
    d = ImageDraw.Draw(im)
    # 选一个能塞进 60x22 的字号
    size = 20
    while size > 8:
        f = load_font(size)
        bb = d.textbbox((0, 0), text, font=f)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        if w <= CW - 2 and h <= CH - 2:
            break
        size -= 1
    f = load_font(size)
    bb = d.textbbox((0, 0), text, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    x = (CW - w) // 2 - bb[0]
    y = (CH - h) // 2 - bb[1]
    d.text((x, y), text, font=f, fill=255)
    # 阈值 -> 1bit，每行 8 字节
    px = im.load()
    out = bytearray(22 * 8)
    for yy in range(CH):
        for xx in range(CW):
            if px[xx, yy] > 96:
                out[yy * 8 + (xx >> 3)] |= 1 << (xx & 7)
    return bytes(out)


def main():
    lines = [
        "// 由 fw/tools/gen_slot_labels.py 生成，勿手改。",
        "// 自定义槽位的状态牌文字位图：60x22 1bit，每行 8 字节，低位在左（与 assets.h 的 PILLTXT_* 同规格）。",
        "#pragma once",
        "#include <Arduino.h>",
        "",
    ]
    for name, text in LABELS:
        bits = render(text)
        arr = ",".join("0x%02X" % b for b in bits)
        lines.append("static const uint8_t SLOTLBL_%s[176] = {%s};  // %s" % (name.upper(), arr, text))
        lines.append("")
    lines.append("struct SlotLabel { const char *name; const uint8_t *bits; };")
    lines.append("static const SlotLabel SLOT_LABELS[] = {")
    for name, text in LABELS:
        lines.append('  {"%s", SLOTLBL_%s},  // %s' % (name, name.upper(), text))
    lines.append("};")
    lines.append("static const int SLOT_LABEL_N = sizeof(SLOT_LABELS) / sizeof(SLOT_LABELS[0]);")
    lines.append("")
    lines.append("// 找不到返回 nullptr（固件会退回 ASCII 显示槽位名）")
    lines.append("static inline const uint8_t *slotLabelBits(const char *n) {")
    lines.append("  if (!n) return nullptr;")
    lines.append("  for (int i = 0; i < SLOT_LABEL_N; i++)")
    lines.append("    if (strcasecmp(SLOT_LABELS[i].name, n) == 0) return SLOT_LABELS[i].bits;")
    lines.append("  return nullptr;")
    lines.append("}")
    lines.append("")
    txt = "\n".join(lines)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(txt)
    print("wrote", OUT, len(txt), "chars")
    # 便于目测：同时导出 PNG
    prev_dir = _os.path.join(_ROOT, "_work", "slotlabels")
    os.makedirs(prev_dir, exist_ok=True)
    for name, text in LABELS:
        im = Image.frombytes("L", (CW, CH), bytes(255 if (render(text)[y * 8 + (x >> 3)] >> (x & 7)) & 1 else 0
                                                for y in range(CH) for x in range(CW)))
        im.resize((CW * 4, CH * 4), Image.NEAREST).save(os.path.join(prev_dir, name + ".png"))
    print("previews ->", prev_dir)


if __name__ == "__main__":
    main()
