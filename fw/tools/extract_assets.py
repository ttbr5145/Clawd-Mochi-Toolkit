"""从控制中心预览 GIF 提取 Clawd-Mochi 内置动画素材 → fw/src/assets.h

产物：
  - 7 个动画（idle/thinking/working/waiting/done/error/sleep）：
      每个动画自带调色板 + 逐帧矩形表（5 字节/矩形：colorIdx,x,y,w,h）
  - 状态牌文字：每个状态一张 60x22 的 1bit 位图（从首帧 pill 里抠出来）
  - 状态牌几何常量 + 圆点颜色表
同时输出重建预览图到 _work/assets/preview/，并逐帧校验重绘 == 原帧。
"""
import json
import argparse
import glob
import os
import sys
import time

import numpy as np
from PIL import Image, ImageSequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gif_compose import load_frames

# ---- 路径：默认相对仓库布局；可用 --src / --out-hdr 或环境变量覆盖 ----
HERE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(FW_DIR)

_ap = argparse.ArgumentParser(description="Extract built-in animations from Clawd-Mochi preview GIFs into assets.h")
_ap.add_argument("--src", default=os.environ.get("MOCHI_ANIM_DIR",
                os.path.join(ROOT, "_work", "Clawd-Mochi.exe_extracted", "web_ui", "assets", "animations")),
                help="directory containing 01_idle_*.gif .. 07_sleep_*.gif")
_ap.add_argument("--out-hdr", default=os.path.join(FW_DIR, "src", "assets.h"), help="output header path")
_args = _ap.parse_args()

GIF_DIR = _args.src
OUT_DIR = os.path.join(ROOT, "_work", "assets")
PREV = os.path.join(OUT_DIR, "preview")
HDR = _args.out_hdr

ANIMS = [
    ("idle",     "01_idle_待机中.gif"),
    ("thinking", "02_thinking_思考中.gif"),
    ("working",  "03_working_工作中.gif"),
    ("waiting",  "04_waiting_等待你.gif"),
    ("done",     "05_done_已完成.gif"),
    ("error",    "06_error_出错了.gif"),
    ("sleep",    "07_sleep_休息中.gif"),
]
W, H = 240, 240
STAGE_H = 180
PILL_Y = 180
TEXT_X, TEXT_Y, TEXT_W, TEXT_H = 90, 199, 60, 22


def log(*a):
    print(*a, flush=True)


def rgb565(c):
    r, g, b = int(c[0]), int(c[1]), int(c[2])
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def decompose(a, key):
    """a: (h,w,3)；key: color tuple -> palette idx。返回 [(cidx,x,y,w,h)]，覆盖整幅图。"""
    h, w = a.shape[0], a.shape[1]
    kidx = np.zeros((h, w), dtype=np.int16) - 1
    for color, i in key.items():
        m = np.all(a == color, axis=2)
        kidx[m] = i
    if (kidx < 0).any():
        raise RuntimeError("palette 未覆盖全部颜色")
    rows = []
    for y in range(h):
        row = kidx[y]
        change = np.nonzero(row[1:] != row[:-1])[0] + 1
        starts = np.concatenate(([0], change))
        ends = np.concatenate((change, [w]))
        rows.append([(int(s), int(e - s), int(row[s])) for s, e in zip(starts, ends)])
    active, rects = {}, []
    for y in range(h):
        segs = set(rows[y])
        for k in list(active):
            if k not in segs:
                y0 = active.pop(k)
                (x, ww, c) = k
                rects.append((c, x, y0, ww, y - y0))
        for seg in segs:
            if seg not in active:
                active[seg] = y
    for (x, ww, c), y0 in active.items():
        rects.append((c, x, y0, ww, h - y0))
    rects.sort(key=lambda r: (r[2], r[1]))
    return rects


def render(rects, palette, w, h):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for (cidx, x, y, ww, hh) in rects:
        img[y:y + hh, x:x + ww] = palette[cidx]
    return img


def emit_u8(lines, name, arr):
    lines.append("static const uint8_t %s[%d] = {" % (name, len(arr)))
    for i in range(0, len(arr), 24):
        lines.append("  " + ",".join(str(v) for v in arr[i:i + 24]) + ",")
    lines.append("};")
    lines.append("")


def emit_u16(lines, name, arr):
    lines.append("static const uint16_t %s[%d] = {%s};" % (
        name, len(arr), ",".join("0x%04X" % v for v in arr)))
    lines.append("")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PREV, exist_ok=True)
    t0 = time.time()

    frames_by_anim = {}
    for name, fn in ANIMS:
        path = os.path.join(GIF_DIR, fn)
        if not os.path.exists(path):
            # 允许文件名前缀匹配：01_idle_*.gif（解包不同版本时中文后缀可能不同）
            cand = sorted(glob.glob(os.path.join(GIF_DIR, fn[:2] + "_*")))
            if cand:
                path = cand[0]
        # 关键：必须用 gif_compose.load_frames 合成局部帧。
        # 直接 ImageSequence.Iterator + convert("RGB") 会把 tile 之外填成 GIF 逻辑背景色，
        # 导致 07_sleep 后续帧被读成"奶白 + 黑卡片"。
        fr = load_frames(path)
        durs = []
        im = Image.open(path)
        for f in ImageSequence.Iterator(im):
            durs.append(f.info.get("duration", 120))
        frames_by_anim[name] = (fr, durs)
        log(f"loaded {name}: {len(fr)} frames, durations {sorted(set(durs))}")

    lines = []
    lines.append("// 自动生成，勿手改：fw/tools/extract_assets.py 从控制中心预览 GIF 提取")
    lines.append("#pragma once")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append(f"#define ANIM_STAGE_W {W}")
    lines.append(f"#define ANIM_STAGE_H {STAGE_H}")
    lines.append(f"#define ANIM_SCREEN_H {H}")
    lines.append("")
    lines.append("#define PILL_X 29")
    lines.append("#define PILL_Y 190")
    lines.append("#define PILL_W 182")
    lines.append("#define PILL_H 41")
    lines.append("#define PILL_R 10")
    lines.append("#define PILL_DOT_X 47")
    lines.append("#define PILL_DOT_Y 205")
    lines.append("#define PILL_DOT_W 11")
    lines.append(f"#define PILL_TEXT_X {TEXT_X}")
    lines.append(f"#define PILL_TEXT_Y {TEXT_Y}")
    lines.append(f"#define PILL_TEXT_W {TEXT_W}")
    lines.append(f"#define PILL_TEXT_H {TEXT_H}")
    lines.append("")
    lines.append("typedef struct {")
    lines.append("  const uint16_t *pal;")
    lines.append("  const uint8_t  *rects;      // 5 字节/矩形: palIdx,x,y,w,h")
    lines.append("  const uint16_t *frame_rstart;")
    lines.append("  const uint16_t *frame_rcount;")
    lines.append("  const uint8_t  *frame_dur10;")
    lines.append("  uint8_t   frame_n;")
    lines.append("  uint8_t   pal_n;")
    lines.append("  uint16_t  bg;")
    lines.append("} AnimDef;")
    lines.append("")

    defs = []
    total_rects = 0
    total_frames = 0
    pill_bmps = {}
    pill_dot = []
    bgs = []
    for idx, (name, fn) in enumerate(ANIMS):
        frames, durs = frames_by_anim[name]
        stage0 = frames[0][:STAGE_H]
        bg = tuple(int(v) for v in stage0[0, 0])
        cols = sorted({tuple(int(v) for v in c) for f in frames
                       for c in np.unique(f[:STAGE_H].reshape(-1, 3), axis=0)})
        # bg 放 0
        if bg in cols:
            cols.remove(bg)
        palette = [bg] + cols
        key = {c: i for i, c in enumerate(palette)}
        all_rects, rstart, rcount, dur10 = [], [], [], []
        worst = 0.0
        for fi, (a, dur) in enumerate(zip(frames, durs)):
            stage = a[:STAGE_H]
            rects = decompose(stage, key)
            img = render(rects, palette, W, STAGE_H)
            if not np.array_equal(img, stage):
                diff = float(np.abs(img.astype(np.int32) - stage.astype(np.int32)).mean())
                worst = max(worst, diff)
            rstart.append(len(all_rects))
            rcount.append(len(rects))
            dur10.append(max(1, min(255, int(round(dur / 10)))))
            all_rects.extend(rects)
            # 预览
            if fi in (0, len(frames) // 2):
                out = a.copy()
                out[:STAGE_H] = img
                Image.fromarray(out).save(os.path.join(PREV, f"{idx}_{name}_f{fi}.png"))
        total_rects += len(all_rects)
        total_frames += len(frames)
        log(f"{name}: colors={len(palette)} frames={len(frames)} rects={len(all_rects)} "
            f"rects/frame={len(all_rects)/len(frames):.1f} meanDiff={worst:.3f}")

        emit_u16(lines, f"PAL_{name.upper()}", [rgb565(c) for c in palette])
        emit_u16(lines, f"RCNT_{name.upper()}", rcount)
        emit_u8(lines, f"DUR_{name.upper()}", dur10)
        emit_u16(lines, f"RSTART_{name.upper()}", rstart)
        flat = []
        for (c, x, y, ww, hh) in all_rects:
            flat.extend([c, x, y, ww, hh])
        emit_u8(lines, f"RECTS_{name.upper()}", flat)
        defs.append((idx, name, len(palette), len(frames), rgb565(bg)))
        bgs.append(rgb565(bg))

        # 状态牌文字位图
        pill = frames[0][TEXT_Y:TEXT_Y + TEXT_H, TEXT_X:TEXT_X + TEXT_W].astype(np.int32)
        white = np.array([0xFF, 0xF6, 0xE7])
        dist = np.abs(pill - white).sum(axis=2)
        mask = (dist < 120).astype(np.uint8)
        bmp = []
        for y in range(TEXT_H):
            for bx in range(0, TEXT_W, 8):
                b = 0
                for k in range(8):
                    xx = bx + k
                    if xx < TEXT_W and mask[y, xx]:
                        b |= 1 << k
                bmp.append(b)
        pill_bmps[name] = bmp
        # 圆点颜色：pill 区域里除 bg/fill/border/text 之外的主色
        first = frames[0][PILL_Y:H]
        pcols, pcnt = np.unique(first.reshape(-1, 3), axis=0, return_counts=True)
        dot = (0xFF, 0xD5, 0xA4)
        for c, n in zip(pcols, pcnt):
            t = tuple(int(v) for v in c)
            if t in ((0x1A, 0x1B, 0x1F), (0xFF, 0xD5, 0xA4), (0xFF, 0xF6, 0xE7), bg):
                continue
            dot = t
        pill_dot.append(rgb565(dot))
        log(f"   pill: textpx={int(mask.sum())} dot=#{dot[0]:02X}{dot[1]:02X}{dot[2]:02X}")

    # 定义表
    lines.append("#define ANIM_N %d" % len(ANIMS))
    lines.append("static const AnimDef ANIMS[ANIM_N] = {")
    for idx, name, pal_n, frm_n, bg in defs:
        U = name.upper()
        lines.append(f"  {{ PAL_{U}, RECTS_{U}, RSTART_{U}, RCNT_{U}, DUR_{U}, {frm_n}, {pal_n}, 0x{bg:04X} }},")
    lines.append("};")
    lines.append("")
    lines.append("#define ANIM_IDLE 0")
    lines.append("#define ANIM_THINKING 1")
    lines.append("#define ANIM_WORKING 2")
    lines.append("#define ANIM_WAITING 3")
    lines.append("#define ANIM_DONE 4")
    lines.append("#define ANIM_ERROR 5")
    lines.append("#define ANIM_SLEEP 6")
    lines.append("")
    lines.append("#define PILL_FILL 0x1903")   # #1A1B1F
    lines.append("#define PILL_BORDER 0xFFD4") # #FFD5A4
    lines.append("#define PILL_TEXTCOL 0xFF7C") # #FFF6E7
    lines.append("")
    lines.append("static const uint16_t PILL_DOT_COLOR[ANIM_N] = {%s};" %
                 ",".join("0x%04X" % v for v in pill_dot))
    lines.append("")
    for idx, (name, _) in enumerate(ANIMS):
        emit_u8(lines, f"PILLTXT_{name.upper()}", pill_bmps[name])

    open(HDR, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    log(f"\nrects={total_rects} frames={total_frames} header={os.path.getsize(HDR)}B "
        f"({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
