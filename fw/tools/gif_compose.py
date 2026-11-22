import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FW = _os.path.dirname(_HERE)
_ROOT = _os.path.dirname(_FW)
"""GIF 逐帧合成器：正确处理局部帧(tile)、透明度、disposal，返回 240x240 RGB 帧列表。

背景/为什么需要它（本项目实测）：
- `07_sleep_休息中.gif` 第 1..35 帧是"局部帧"，只编码变化区域（tile 如 (29,121,211,231)）。
- PIL 的 `ImageSequence` / 直接 `convert("RGB")` 会把 tile 之外的像素填成 GIF 的
  "逻辑背景色"，该 GIF 的这一步填出来是奶白 #FFF6E7（导出时背景索引写错），
  于是后续帧被读成"奶白底 + 黑卡片"，固件忠实渲染后用户看到「休息中」变成黑白。
- 实际美术：第 0 帧是全幅 240×240、黑底 + 橙宠物，所以正确合成 = tile 之外保持上一帧内容，
  需要清理时按"该动画自己的底色"（第 0 帧左上角像素色）清理，而不是 GIF 声明的背景色。

用法：
    from gif_compose import load_frames
    frames = load_frames(r"...\07_sleep_休息中.gif")      # -> [np.uint8(240,240,3), ...]
    frames = load_frames(gif, bg=(205, 52, 0))           # 也可显式指定清理底色
"""

import numpy as np
from PIL import Image


def _frame_gces(raw):
    """按出现顺序取出所有 Graphic Control Extension：(disposal, has_transparency, trans_idx)。"""
    out = []
    i = 0
    n = len(raw)
    while i < n - 2:
        if raw[i] == 0x21 and raw[i + 1] == 0xF9:
            flags = raw[i + 3]
            out.append(((flags >> 2) & 0x07, bool(flags & 0x01), raw[i + 6]))
            i += 8
            continue
        i += 1
    return out


def load_frames(path, bg=None, verbose=False, apply_disposal=False):
    """返回合成后的 RGB 帧列表（np.uint8, H×W×3）。

    bg=None 时用第 0 帧左上角像素作为清理色（每个动画自己的底色）。

    apply_disposal：默认 False。本项目所有 7 个 GIF 的 GCE 都标了 disposal=2
    （restore to background），但实际导出时是"局部帧叠加"的语义：真按 disposal=2
    清理会把第 0 帧画好的宠物主体擦掉，剩下的只是碎片。因此默认按"叠加"合成，
    只在需要时显式开启 disposal 清理。
    """
    im = Image.open(path)
    gces = _frame_gces(open(path, "rb").read())
    n = getattr(im, "n_frames", 1)

    # 先取第 0 帧，确定画布与清理底色
    im.seek(0)
    full_w, full_h = im.size
    first = im.convert("RGB")
    first_np = np.array(first)
    if bg is None:
        bg = tuple(int(v) for v in first_np[0, 0])

    canvas = Image.new("RGB", (full_w, full_h), bg)
    out = []
    prev_bbox = None
    prev_disposal = 1

    for i in range(n):
        im.seek(i)
        bbox = im.tile[0].extents if im.tile else (0, 0, full_w, full_h)

        # 1) 先执行上一帧的 disposal=2：把上一帧的 tile 区域清成底色
        if prev_disposal == 2 and prev_bbox is not None:
            x0, y0, x1, y1 = prev_bbox
            canvas.paste(Image.new("RGB", (x1 - x0, y1 - y0), bg), (x0, y0))

        # 2) 贴当前帧的 tile
        rgba = im.convert("RGBA")
        region = rgba.crop(bbox)
        mask = region.getchannel("A")
        if i in gces and gces[i][1]:
            canvas.paste(region.convert("RGB"), (bbox[0], bbox[1]), mask)
        else:
            canvas.paste(region.convert("RGB"), (bbox[0], bbox[1]))

        # 3) 记录本帧
        out.append(np.array(canvas))
        if verbose:
            print("frame %d bbox %s disposal %s" % (i, bbox, gces[i][0] if i < len(gces) else "?"))
        prev_bbox = bbox
        prev_disposal = gces[i][0] if i < len(gces) else 1

    return out


if __name__ == "__main__":
    import glob
    import os

    DIR = _os.path.join(_ROOT, "_work", "Clawd-Mochi.exe_extracted", "web_ui", "assets", "animations")
    for p in ["07_sleep", "01_idle", "02_thinking", "03_working", "04_waiting", "05_done", "06_error"]:
        g = sorted(glob.glob(os.path.join(DIR, p + "*.gif")))[0]
        fr = load_frames(g)
        corners = {tuple(f[5, 5]) for f in fr}
        print(os.path.basename(g), "frames", len(fr), "corner colors", sorted(corners)[:4])
