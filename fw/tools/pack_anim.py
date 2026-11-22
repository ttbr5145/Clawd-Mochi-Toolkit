import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FW = _os.path.dirname(_HERE)
_ROOT = _os.path.dirname(_FW)
"""把 GIF / PNG / WebP 打包成 Clawd-Mochi 自定义固件的素材格式。

用法：
  python pack_anim.py kill.gif                     -> kill.cma（动画槽位）
  python pack_anim.py kill.gif --name kill1        -> 指定槽位名
  python pack_anim.py pic.png --rgb                -> pic.rgb（静态 240x180 RGB565）
  python pack_anim.py kill.gif --preview out.png   -> 同时输出重建预览图

动画格式 CMA1（小端）：
  0   'C','M','A','1'
  4   u16 version = 1
  6   u16 pal_n        (<=256)
  8   u16 frame_n      (<=512)
  10  u16 bg_idx       (palette 里当底色的下标)
  12  u16 reserved
  14  u16 reserved
  16  palette  u16[pal_n] (RGB565)
  ..  frames   {u16 dur_ms, u16 rect_n} x frame_n
  ..  rects    5 字节/条：u8 pal_idx, u8 x, u8 y, u8 w, u8 h（按帧顺序）
"""
import argparse
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageSequence

W, H = 240, 180
DEFAULT_BG = (205, 52, 0)  # #CD3400


def rgb565(c):
    r, g, b = int(c[0]), int(c[1]), int(c[2])
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def fit_frame(im, bg):
    """把任意图裁/缩放到 240x180，居中，底色填充。"""
    im = im.convert("RGB")
    if im.size == (240, 240):
        return im.crop((0, 0, 240, 180))
    if im.size == (W, H):
        return im
    scale = min(W / im.width, H / im.height)
    nw, nh = max(1, int(round(im.width * scale))), max(1, int(round(im.height * scale)))
    resized = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), bg)
    canvas.paste(resized, ((W - nw) // 2, (H - nh) // 2))
    return canvas


def build_palette(frames):
    """返回 (palette 列表[(r,g,b)], 映射函数: ndarray(h,w,3)->ndarray(h,w) 索引)。"""
    colors = set()
    for f in frames:
        a = np.asarray(f, dtype=np.uint8).reshape(-1, 3)
        # 抽样加速（大图）
        step = max(1, a.shape[0] // 60000)
        for px in a[::step]:
            colors.add((int(px[0]), int(px[1]), int(px[2])))
    colors = sorted(colors)
    if len(colors) <= 255:
        pal = list(colors)
        lut = {c: i for i, c in enumerate(pal)}
        bg_idx = 0
        bg = tuple(frames[0].getpixel((0, 0)))
        if bg in lut:
            bg_idx = lut[bg]
        else:
            pal.append(bg)
            lut[bg] = len(pal) - 1
            bg_idx = len(pal) - 1
        # 把 bg 换到 0 号位，方便固件把 0 号色当底色
        if bg_idx != 0:
            pal[0], pal[bg_idx] = pal[bg_idx], pal[0]
            lut = {c: i for i, c in enumerate(pal)}
            bg_idx = 0

        def mapex(a):
            flat = a.reshape(-1, 3)
            out = np.empty(flat.shape[0], dtype=np.uint8)
            # 精确匹配
            keys = [tuple(int(v) for v in px) for px in flat]
            uniq = {}
            for i, k in enumerate(keys):
                v = uniq.get(k)
                if v is None:
                    v = lut[k]
                    uniq[k] = v
                out[i] = v
            return out.reshape(a.shape[:2])

        return pal, mapex, 0

    # 多于 256 色：用第一帧量化出的调色板做最近邻映射
    sample = frames[0].quantize(colors=255, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    raw = sample.getpalette() or []
    ncol = min(255, len(raw) // 3)
    if ncol < 1:
        raise SystemExit("palette build failed")
    pal = [(raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]) for i in range(ncol)]
    bg = tuple(frames[0].getpixel((0, 0)))
    pal = [bg] + [c for c in pal if c != bg]
    pal = pal[:256]
    arr = np.array(pal, dtype=np.int32)

    def mapex(a):
        flat = a.reshape(-1, 3).astype(np.int32)
        d = ((flat[:, None, :] - arr[None, :, :]) ** 2).sum(axis=2)
        return d.argmin(axis=1).astype(np.uint8).reshape(a.shape[:2])

    return pal, mapex, 0


def decompose(kidx):
    """kidx: (h,w) uint8。逐行 RLE + 纵向合并 -> [(idx,x,y,w,h)]。idx==0 的跳过。"""
    h, w = kidx.shape
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
                if c:
                    rects.append((c, x, y0, ww, y - y0))
        for seg in segs:
            if seg not in active:
                active[seg] = y
    for (x, ww, c), y0 in active.items():
        if c:
            rects.append((c, x, y0, ww, h - y0))
    rects.sort(key=lambda r: (r[2], r[1]))
    return rects


def render(rects, pal, bg):
    a = np.zeros((H, W, 3), dtype=np.uint8)
    a[:, :] = pal[bg]
    for c, x, y, w, h in rects:
        a[y:y + h, x:x + w] = pal[c]
    return Image.fromarray(a, "RGB")


def load_frames(path, bg):
    im = Image.open(path)
    frames, durs = [], []
    for f in ImageSequence.Iterator(im):
        frames.append(fit_frame(f, bg))
        durs.append(int(f.info.get("duration") or im.info.get("duration") or 100))
    return frames, durs


def write_cma(path, pal, frames, durs, bg_idx):
    all_rects = []
    frame_tab = []
    for kidx in frames:
        rects = decompose(kidx)
        frame_tab.append((max(1, min(65535, durs[len(frame_tab)])), len(rects)))
        all_rects.extend(rects)
    with open(path, "wb") as f:
        f.write(b"CMA1")
        f.write(struct.pack("<HHHHHH", 1, len(pal), len(frame_tab), bg_idx, 0, 0))
        for c in pal:
            f.write(struct.pack("<H", rgb565(c)))
        for dur, n in frame_tab:
            f.write(struct.pack("<HH", dur, n))
        for c, x, y, w, h in all_rects:
            f.write(bytes((c & 0xFF, x & 0xFF, y & 0xFF, w & 0xFF, h & 0xFF)))
    return len(all_rects), len(frames), len(pal)


def write_rgb(path, frame):
    a = np.asarray(frame)
    out = np.empty((H, W, 2), dtype=np.uint8)
    r = (a[:, :, 0] & 0xF8) >> 3
    g = (a[:, :, 1] & 0xFC) >> 2
    b = a[:, :, 2] >> 3
    v = (r.astype(np.uint16) << 11) | (g.astype(np.uint16) << 5) | b
    out[:, :, 0] = v & 0xFF
    out[:, :, 1] = v >> 8
    with open(path, "wb") as f:
        f.write(out.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--name", default="")
    ap.add_argument("--outdir", default=_os.path.join(_ROOT, "_work", "anim_pack"))
    ap.add_argument("--rgb", action="store_true", help="输出静态 RGB565 图（240x180）")
    ap.add_argument("--preview", default="", help="输出重建预览（仅单帧或第一帧）")
    ap.add_argument("--bg", default="", help="底色 RRGGBB，默认 #CD3400")
    args = ap.parse_args()

    bg = DEFAULT_BG
    if args.bg:
        h = args.bg.lstrip("#")
        bg = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    os.makedirs(args.outdir, exist_ok=True)
    base = args.name or os.path.splitext(os.path.basename(args.input))[0]
    base = "".join(ch for ch in base.lower() if ch.isalnum() or ch in "-_") or "slot"

    frames_rgb, durs = load_frames(args.input, bg)
    pal, mapex, bg_idx = build_palette(frames_rgb)
    kidx_frames = [mapex(np.asarray(f)) for f in frames_rgb]

    if args.rgb:
        out = os.path.join(args.outdir, base + ".rgb")
        write_rgb(out, frames_rgb[0])
        print(f"wrote {out} ({os.path.getsize(out)} bytes, static 240x180 RGB565)")
        return

    out = os.path.join(args.outdir, base + ".cma")
    nr, nf, npal = write_cma(out, pal, kidx_frames, durs, bg_idx)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)  frames={nf} pal={npal} rects={nr} dur={durs[:4]}...")

    if args.preview:
        rects = decompose(kidx_frames[0])
        render(rects, pal, bg_idx).save(args.preview)
        print("preview ->", args.preview)


if __name__ == "__main__":
    main()
