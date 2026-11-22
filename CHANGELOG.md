# Changelog

All notable changes to this project. Firmware versions are also used as release tags
(`fw-v0.x.y`); the toolkit itself is versioned separately (`v1.0.0`, ...).

## Toolkit v1.0.0 — 2026-11-22

First public release of the toolkit.

- `ext/` — desktop-side extensions for Clawd-Mochi:
  - `mochi_bridge.py` extended event bridge on `127.0.0.1:18894` (all 13 event names,
    terminal text, progress bar, background colour, speed, backlight).
  - `mochi_hook.py` single-shot hook client (~35-40 ms per call vs ~630-770 ms for the
    stock PowerShell `-EncodedCommand` hook).
  - `dsh-plugin/index.js` DeepSeek Harness status plugin with finer-grained states.
  - `examples/claude-code-extra-hooks.json` extra Claude Code hooks (Notification,
    PreCompact, PostCompact, SubagentStart, SubagentStop) using curl.
  - `cs2_mochi.py` CS2 Game State Integration receiver (`18895`) with kill tiers,
    headshot/killstreak/death/round reactions, web dashboard and `/replay`.
- `fw/` — self-built firmware source:
  - 13 AI events mapped to the six built-in animations, rebuilt pixel-perfect from the
    official preview GIFs (251 frames, `meanDiff = 0.000`).
  - Unlimited custom animation slots (`.cma`) and static image slots (`.rgb`) in LittleFS.
  - Full compatibility with the official control centre HTTP API, plus `/slot/*`,
    `/screenshot.bmp`, `/panel`, `/health`, `/anim/list`.
  - Official USB/serial control protocol (control centre "USB wired" mode), serial
    console, multi-network auto-connect and `/net/get` network diagnostics.
- Docs: root README, `ext/README.md` (boundary analysis + measured numbers),
  `fw/README.md` (API, asset formats, flash/rollback, test log).

## Firmware 0.1.4

- Official USB/serial control protocol: `PING`, `EVENT <name>`, `STATE`,
  `VIEW idle|sleep`, `BACKLIGHT`, `SPEED`, `BG` — the official control centre can drive
  the device over USB when the PC and the pet are on different networks.
- Serial console (115200 8N1): `help / ip / scan / state / net <url> / wifi <ssid> [pass] /
  save <ssid> [pass] / forget / reboot`.
- Multi-network auto-connect (`DEFAULT_NETS`, now supplied via git-ignored
  `config_secrets.h`).
- New diagnostics endpoints: `/net/get?url=&follow=`, `/wifi/status`, `/wifi/try`.
- Image size ~1.2 MB (HTTPClient / mbedTLS pulled in).

## Firmware 0.1.2

- Slot playback priority: while a kill/death/round slot animation is playing, the 13
  agent hook events no longer interrupt it.
- Includes the 0.1.1 sleep-animation fix.

## Firmware 0.1.1-sleepfix

- Fixed the built-in "sleeping" animation: frames 1..35 of the official preview GIF are
  partial frames; the old extractor filled the tile outside with the GIF background
  colour (cream), which showed as a black-and-white screen. Added
  `fw/tools/gif_compose.py` (tile compositing) and re-extracted all seven animations
  (meanDiff = 0.000 on every frame).

## Firmware 0.1.0-inv

- First working custom firmware: unlimited custom slots, extended HTTP API, panel
  inversion fix (default `inv=1`; without inversion the orange turns light blue).
