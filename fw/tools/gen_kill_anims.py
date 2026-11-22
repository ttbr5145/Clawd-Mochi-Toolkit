import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FW = _os.path.dirname(_HERE)
_ROOT = _os.path.dirname(_FW)
"""生成 Clawd-Mochi 自定义动画（击杀/阵亡/回合）——与原机像素风一致。

产物（GIF，240x180 舞台，整屏）：
  _work/kill_anim/kill1.gif ... kill5.gif, death.gif, roundwin.gif, roundlose.gif
再配 fw/tools/pack_anim.py 打成 .cma 上传到同名槽位。

风格：纯色块 + 无抗锯齿 + 与内置动画同色系（身体 #D58162 / 阴影 #080C10 / 眼 #000000）。
"""
import argparse
import math
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

W, H = 240, 180
BODY = (213, 129, 98)
BODY_D = (166, 96, 70)
DARK = (8, 12, 16)
WHITE = (255, 246, 231)
EYE = (0, 0, 0)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]

TIERS = {
    1: ("单杀", (0, 255, 102), (0, 90, 40)),
    2: ("双杀", (255, 196, 0), (110, 70, 0)),
    3: ("三杀", (255, 106, 0), (110, 40, 0)),
    4: ("四杀", (255, 45, 0), (110, 10, 0)),
    5: ("ACE", (255, 0, 255), (90, 0, 90)),
}


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_pet(d, cx, cy, scale=1.0, squint=False, tilt=0):
    """在 (cx,cy) 处画一只 Clawd（矩形拼装，scale 用整数像素放大思路近似）。"""
    s = scale
    bw, bh = int(106 * s), int(68 * s)
    x0 = int(cx - bw / 2)
    y0 = int(cy - bh / 2)
    # 阴影条
    d.rectangle([x0 + 10, y0 + bh + 20, x0 + bw - 10, y0 + bh + 28], fill=DARK)
    # 身体
    d.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1], fill=BODY)
    # 顶边高光
    d.rectangle([x0, y0, x0 + bw - 1, y0 + 3], fill=(166, 101, 90))
    # 两侧小手/耳
    ear = int(38 * s)
    ey = y0 + int(29 * s)
    d.rectangle([x0 - ear + 6, ey, x0 - 1, ey + int(10 * s) - 1], fill=BODY)
    d.rectangle([x0 + bw, ey, x0 + bw + ear - 7, ey + int(10 * s) - 1], fill=BODY)
    # 眼
    ew, eh = max(3, int(8 * s)), max(4, int(20 * s))
    lex = x0 + int(20 * s)
    rex = x0 + bw - int(28 * s)
    ety = y0 + int(19 * s)
    if squint:
        d.rectangle([lex, ety + eh // 2 - 2, lex + ew - 1, ety + eh // 2 + 1], fill=EYE)
        d.rectangle([rex, ety + eh // 2 - 2, rex + ew - 1, ety + eh // 2 + 1], fill=EYE)
    else:
        d.rectangle([lex, ety, lex + ew - 1, ety + eh - 1], fill=EYE)
        d.rectangle([rex, ety, rex + ew - 1, ety + eh - 1], fill=EYE)
    # 四腿
    lw = max(2, int(9 * s))
    ly = y0 + bh - int(12 * s)
    for lx in (x0 + int(10 * s), x0 + int(29 * s), x0 + int(68 * s), x0 + int(87 * s)):
        d.rectangle([lx, ly, lx + lw - 1, y0 + bh + int(19 * s)], fill=BODY)


def draw_text(d, text, cx, cy, size, fg, shadow):
    font = load_font(size)
    tw = d.textbbox((0, 0), text, font=font)
    w, h = tw[2] - tw[0], tw[3] - tw[1]
    x, y = cx - w / 2 - tw[0], cy - h / 2 - tw[1]
    d.text((x + 3, y + 3), text, font=font, fill=shadow)
    d.text((x, y), text, font=font, fill=fg)


def ring(d, cx, cy, r, color, width=4):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)


def frame_kill(label, bg, bg_dark, t, total=12):
    """t: 0..1 进度。返回 RGB 图。"""
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)

    # 背景：两条斜向暗带，随进度滚动，制造动感
    off = int(t * 60)
    for i in range(-2, 8):
        x = i * 60 - off
        d.polygon([(x, 0), (x + 24, 0), (x - 40, H), (x - 64, H)], fill=bg_dark)

    # 中央爆发环
    if t < 0.6:
        for k in range(3):
            r = int(30 + (t * 3 + k * 0.33) * 90)
            ring(d, W // 2, 84, r, WHITE if k % 2 == 0 else bg_dark, width=3)

    # 宠物：先放大后回落
    if t < 0.25:
        sc = 1.0 + t / 0.25 * 0.18
    elif t < 0.55:
        sc = 1.18 - (t - 0.25) / 0.30 * 0.10
    else:
        sc = 1.08
    bob = int(math.sin(t * math.pi * 2) * 4)
    draw_pet(d, W // 2, 80 + bob, scale=sc, squint=(t > 0.5))

    # 文字：弹入 + 抖动
    size = int(34 + 10 * min(1, t * 3))
    jitter = 2 if t < 0.35 else 0
    draw_text(d, label, W // 2 + jitter, 148, size, WHITE, DARK)

    # 四角星芒（放在宠物外侧，避免糊在脸上）
    for ang in (0, 90, 180, 270):
        a = math.radians(ang + t * 90)
        r0, r1 = 62, 62 + int(10 + 8 * math.sin(t * 6))
        x0, y0 = W // 2 + math.cos(a) * r0, 84 + math.sin(a) * r0
        x1, y1 = W // 2 + math.cos(a) * r1, 84 + math.sin(a) * r1
        d.line([x0, y0, x1, y1], fill=WHITE, width=3)
    return im


def frame_death(t=0.0):
    im = Image.new("RGB", (W, H), (60, 16, 16))
    d = ImageDraw.Draw(im)
    # 暗色斜纹
    for i in range(-2, 8):
        x = i * 50
        d.polygon([(x, 0), (x + 18, 0), (x - 50, H), (x - 68, H)], fill=(44, 10, 10))
    # 倒地：宠物横放
    pet = Image.new("RGBA", (170, 120), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pet)
    draw_pet(pd, 85, 60, scale=0.9, squint=True)
    pet = pet.rotate(90, expand=True)
    im.paste(pet, (34, 46), pet)
    draw_text(d, "阵亡", W // 2, 26, 30, (255, 210, 210), (30, 0, 0))
    # 血条见底（每帧随机抖动长度）
    d.rectangle([30, 160, 210, 176], fill=(30, 6, 6))
    w = 26 + int(6 * math.sin(t * 6.28))
    d.rectangle([34, 164, 34 + w, 172], fill=(210, 40, 40))
    # 心跳一样的暗度脉动
    k = 0.80 + 0.20 * abs(math.sin(t * math.pi))
    return ImageEnhance.Brightness(im).enhance(k)


def frame_round(win, t=0.0):
    top = (12, 90, 40) if win else (20, 40, 90)
    dark = (8, 62, 28) if win else (12, 26, 64)
    im = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(im)
    for i in range(-2, 9):
        x = i * 46
        d.polygon([(x, 0), (x + 20, 0), (x - 46, H), (x - 66, H)], fill=dark)
    # 胜利：宠物上下跳；失败：宠物下沉
    bob = int(6 * math.sin(t * 6.28)) if win else int(4 * t)
    draw_pet(d, W // 2, 82 + bob, scale=1.05, squint=not win)
    draw_text(d, "胜利" if win else "失败", W // 2, 152, 40, WHITE, DARK)
    return im


def save_gif(frames, path, dur=100):
    """用统一调色板 + 关抖动保存，保证色块干净（固件端矩形表才能紧凑）。"""
    p0 = frames[0].convert("P", palette=Image.ADAPTIVE, colors=24, dither=Image.Dither.NONE)
    pframes = [p0] + [f.quantize(palette=p0, dither=Image.Dither.NONE) for f in frames[1:]]
    pframes[0].save(path, save_all=True, append_images=pframes[1:], duration=dur, loop=0, optimize=False)
    print("wrote", path, len(frames), "frames")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=_os.path.join(_ROOT, "_work", "kill_anim"))
    ap.add_argument("--sheet", default="")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    all_first = []
    for tier, (label, bg, dark) in TIERS.items():
        frames = [frame_kill(label, bg, dark, i / 11.0) for i in range(12)]
        save_gif(frames, os.path.join(args.outdir, f"kill{tier}.gif"), 100)
        all_first.append(frames[6])

    d = [frame_death(i / 7.0) for i in range(8)]
    save_gif(d, os.path.join(args.outdir, "death.gif"), 120)
    all_first.append(d[0])

    w = [frame_round(True, i / 7.0) for i in range(8)]
    save_gif(w, os.path.join(args.outdir, "roundwin.gif"), 120)
    all_first.append(w[0])
    l = [frame_round(False, i / 7.0) for i in range(8)]
    save_gif(l, os.path.join(args.outdir, "roundlose.gif"), 120)
    all_first.append(l[0])

    if args.sheet:
        cols = 4
        rows = (len(all_first) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * W, rows * H), (20, 20, 20))
        for i, im in enumerate(all_first):
            sheet.paste(im, ((i % cols) * W, (i // cols) * H))
        sheet.save(args.sheet)
        print("sheet ->", args.sheet)


if __name__ == "__main__":
    main()
