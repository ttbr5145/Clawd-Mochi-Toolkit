import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FW = _os.path.dirname(_HERE)
_ROOT = _os.path.dirname(_FW)
"""测试设备 /image/upload （控制中心用的 multipart 协议）与 /image/reset。

先生成一张 240x180 的测试图（RGB565 小端），用 multipart field name="image"、
filename="<state>.rgb" 上传；再从 /images 看 custom 标记；切到该状态看效果。
"""
import json
import math
import os
import urllib.request

HOST = "http://clawd-mochi.local"
BOUND = "ClawdMochiImageBoundary"
OUT = _os.path.join(_ROOT, "_work", "testimg")


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def make_test_image():
    """蓝紫渐变 + 一行白字方块，方便目测。"""
    buf = bytearray(240 * 180 * 2)
    for y in range(180):
        for x in range(240):
            v = rgb565(int(40 + 60 * x / 240), int(30 + 40 * y / 180), 200)
            i = (y * 240 + x) * 2
            buf[i] = v & 0xFF
            buf[i + 1] = v >> 8
    # 画个白色方框，确定方向（左上角三角形标记）
    for x in range(240):
        for y in range(180):
            mark = (x < 40 and y < 40 and (x + y) < 40) or (x > 200 and y > 140) or \
                   abs(y - 90) < 3 or abs(x - 120) < 3
            if mark:
                v = rgb565(255, 255, 255)
                i = (y * 240 + x) * 2
                buf[i] = v & 0xFF
                buf[i + 1] = v >> 8
    return bytes(buf)


def multipart(payload, filename):
    head = (
        f"--{BOUND}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{BOUND}--\r\n".encode()
    return head + payload + tail


def post(url, body, ctype):
    r = urllib.request.Request(url, data=body, method="POST")
    r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=20) as resp:
        return resp.status, resp.read().decode()


def get(url):
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.status, resp.read().decode()


def main():
    os.makedirs(OUT, exist_ok=True)
    img = make_test_image()
    p = os.path.join(OUT, "2.rgb")
    open(p, "wb").write(img)
    print("test image:", p, len(img), "bytes")

    body = multipart(img, "2.rgb")
    st, txt = post(HOST + "/image/upload?state=2", body, "multipart/form-data; boundary=" + BOUND)
    print("upload:", st, txt)

    st, txt = get(HOST + "/images")
    print("images:", st, txt)
    j = json.loads(txt)
    print("custom[2]:", j.get("custom", {}).get("2"))

    # 切到 2 号状态（工作中）看底图
    print(get(HOST + "/event?s=coding")[1])
    st, txt = get(HOST + "/state")
    print("state:", txt)

    # 恢复默认
    print(get(HOST + "/image/reset?state=2")[1])
    print("images after reset:", get(HOST + "/images")[1])
    print(get(HOST + "/event?s=idle")[1])


if __name__ == "__main__":
    main()
