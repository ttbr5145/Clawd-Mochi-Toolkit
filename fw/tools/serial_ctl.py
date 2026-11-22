#!/usr/bin/env python3
"""串口控制台工具：读设备 USB CDC 日志 / 发命令。

注意：打开串口会让 ESP32-C3 复位（USB CDC 的 DTR/RTS 行为），所以脚本会先等
"[cmd] ready" 出现再发命令，避免命令丢失。

用法：
  python serial_ctl.py --read 6
  python serial_ctl.py --send "ip" --wait 2
  python serial_ctl.py --send "wifi NEFU-WIFI" --wait 25 --send "ip" --wait 2 --send "net http://x/" --wait 10
"""
import argparse
import time

import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM11")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--send", action="append", default=[], help="要发送的命令（可多次）")
    ap.add_argument("--wait", type=float, default=2.0, help="每条命令后等待秒数")
    ap.add_argument("--read", type=float, default=0.0, help="只读：读多少秒")
    ap.add_argument("--boot-wait", type=float, default=20.0, help="最多等启动多少秒")
    ap.add_argument("--no-boot-wait", action="store_true")
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    time.sleep(0.2)

    def pump(duration, stop_marker=None):
        """打印串口输出；若给了 stop_marker，看到它就提前结束。"""
        end = time.time() + duration
        while time.time() < end:
            line = ser.readline()
            if not line:
                continue
            text = line.decode("utf-8", errors="replace").rstrip()
            print(text, flush=True)
            if stop_marker and stop_marker in text:
                return True
        return False

    if args.read:
        pump(args.read)
        ser.close()
        return

    if not args.no_boot_wait:
        pump(args.boot_wait, stop_marker="[cmd] ready")

    for cmd in args.send:
        print(f">>> {cmd}", flush=True)
        ser.write((cmd + "\r\n").encode())
        ser.flush()
        pump(args.wait)

    ser.close()


if __name__ == "__main__":
    main()
