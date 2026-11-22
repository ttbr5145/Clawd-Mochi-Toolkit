Clawd-Mochi firmware images / flashers
=====================================

IMPORTANT: no firmware BINARIES are shipped in this repository.
The factory firmware is third-party copyrighted code, and every self-built image
embeds artwork that was extracted from the official Clawd-Mochi assets, so
neither can be redistributed here. Build your own image, and make your own
factory backup, as described below.

WHICH FILE TO USE
-----------------
A) Re-flash your self-built firmware (normal case):
     clawdmochi-custom.bin          -> write at 0x10000
   One click: FLASH-custom.bat   (or: FLASH-custom.bat COM11)
   Keeps: bootloader, partition table, WiFi credentials, all custom slots.
   Build it first:  cd fw && pio run
   then copy .pio\build\clawdmochi\firmware.bin  ->  fw\dist\clawdmochi-custom.bin
   (rename per version if you like, e.g. clawdmochi-custom-0.1.4.bin, and edit
    set IMG= in FLASH-custom.bat accordingly)
   Port is usually COM11 (Espressif USB-Serial/JTAG).
   IMPORTANT: if the Clawd-Mochi control center is set to "USB wired" mode it
   owns COM11 and esptool will say the port is busy. Switch the control center
   back to Wi-Fi mode first (UI, or POST /api/device/config with
   {"mode":"wifi","host":"clawd-mochi.local"} to 127.0.0.1:18893), then flash.

B) Go back to the original factory firmware:
     clawdmochi-stock-app.bin       -> write at 0x10000
   One click: RESTORE-factory-app.bat
   Keeps WiFi credentials and custom slots (they are just ignored).
   You must supply this file yourself: it is the factory app partition, which you
   can cut out of a full flash backup (step C) at 0x10000 .. 0x310000.

C) Full factory restore (also erases WiFi creds + all slots):
   One click: RESTORE-factory-full.bat
   Writes factory-full-backup.bin at 0x0 (you must supply the 4 MB backup).
   Make the backup while the factory firmware is still installed:
     python -m esptool --chip esp32c3 --port COM11 --baud 460800 read-flash 0x0 0x400000 factory-full-backup.bin
   DO THIS BEFORE flashing your own firmware, or you lose the factory image.

REBUILDING AFTER CODE CHANGES
-----------------------------
  cd <repo>\fw
  pio run
  -> new image: .pio\build\clawdmochi\firmware.bin
  Copy it into this folder as clawdmochi-custom.bin (keep older copies under a
  versioned name if you want a stable "golden" image), then flash that copy.

NOTES
-----
- Only the Wi-Fi firmware variant exists for this project (USB/BLE variants of
  the official firmware are not rebuilt here).
- 0.1.4 and later also speak the official USB/serial protocol, so the control
  center can use "USB wired" mode (mode: usb) when the PC and the pet are on
  different networks. Serial console commands (115200 8N1 on COM11):
    ip | scan | state | net <url> | wifi <ssid> [pass] | save <ssid> [pass]
    | forget | reboot | help
- Manual command equivalent:
    python -m esptool --chip esp32c3 --port COM11 --baud 460800 --after hard-reset write-flash 0x10000 <image>
- If it says "Could not open COM11": unplug/replug the Type-C cable, or hold
  BOOT, tap RST, release BOOT (download mode), then run again.
- After flashing, the device reconnects to WiFi in ~10 s; check:
    http://clawd-mochi.local/state
- Panel is inverse-display: /panel?inv=1 is the correct default (inv=0 gives
  light-blue "ghost" colors). Rotation 2 is correct for the current hardware.

VERSION HISTORY
---------------
  0.1.4  Official USB/serial control protocol (PING, EVENT <name>, STATE,
         VIEW sleep, BACKLIGHT, SPEED, BG -> control center "USB wired" mode)
         + serial console (ip / scan / state / net <url> / wifi / save /
         forget / reboot) + multi-network auto-try + /net/get, /wifi/status,
         /wifi/try diagnostics. Image grew to ~1.2 MB (HTTPClient/mbedTLS).
  0.1.2  Sleep animation fix (GIF partial-frame compositing bug) + slot
         playback priority (while a kill/death/round slot is playing, agent
         hook events do not interrupt it).
  0.1.1-sleepfix  Only the sleep animation fix.
  0.1.0-inv       First usable version + panel inversion fix (default inv=1).
