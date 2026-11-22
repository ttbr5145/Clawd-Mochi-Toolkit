"""把素材上传到 Clawd-Mochi 自定义固件。

用法：
  python upload_slot.py kill1.cma --name kill1           # 动画槽位
  python upload_slot.py kill1.rgb --name kill1           # 静态图槽位
  python upload_slot.py pic.rgb --image 2                # 覆盖 2 号内置状态底图
  python upload_slot.py --list                           # 看设备现有槽位
  python upload_slot.py --delete kill1                   # 删除槽位
  python upload_slot.py --shot shot.bmp                  # 抓设备截图

默认 host 读 %APPDATA%\\ClawdMochi\\settings.json 的 host（clawd-mochi.local）。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BOUNDARY = "ClawdMochiImageBoundary"


def default_host():
    p = os.path.join(os.environ.get("APPDATA", ""), "ClawdMochi", "settings.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("host") or "clawd-mochi.local"
    except Exception:
        return "clawd-mochi.local"


def req(url, data=None, timeout=15, ctype=None):
    r = urllib.request.Request(url, data=data)
    if ctype:
        r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, body


def multipart(field, filename, payload):
    head = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{BOUNDARY}--\r\n".encode()
    return head + payload + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--image", type=int, default=-1, help="覆盖内置状态底图 0..6")
    ap.add_argument("--host", default="")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--delete", default="")
    ap.add_argument("--shot", default="")
    ap.add_argument("--state", action="store_true", help="打印 /state")
    args = ap.parse_args()

    host = args.host or default_host()
    base = f"http://{host}:{args.port}"

    try:
        if args.state:
            st, body = req(base + "/state")
            print(body.decode(errors="replace"))
            return
        if args.list:
            st, body = req(base + "/images")
            print(body.decode(errors="replace"))
            return
        if args.delete:
            st, body = req(base + f"/slot/delete?name={args.delete}")
            print(st, body.decode(errors="replace"))
            return
        if args.shot:
            st, body = req(base + "/screenshot.bmp", timeout=30)
            with open(args.shot, "wb") as f:
                f.write(body)
            print(f"shot {st} {len(body)} bytes -> {args.shot}")
            return
        if not args.file:
            ap.error("需要文件参数（或用 --list/--delete/--shot/--state）")
        payload = open(args.file, "rb").read()
        fn = os.path.basename(args.file)
        if args.image >= 0:
            url = base + f"/image/upload?state={args.image}"
            body = multipart("image", f"{args.image}.rgb", payload)
        else:
            name = args.name or os.path.splitext(fn)[0]
            url = base + f"/slot/upload?name={name}"
            body = multipart("file", fn, payload)
        st, resp = req(url, body, timeout=60, ctype=f"multipart/form-data; boundary={BOUNDARY}")
        print(st, resp.decode(errors="replace"))
    except urllib.error.URLError as e:
        print("ERROR:", e)
        sys.exit(1)
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode(errors="replace"))
        sys.exit(1)


if __name__ == "__main__":
    main()
