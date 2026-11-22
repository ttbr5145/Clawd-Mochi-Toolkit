@echo off
setlocal
rem Flash the self-built Clawd-Mochi firmware (app partition only, at 0x10000).
rem Keeps: bootloader, partition table, NVS (WiFi credentials), LittleFS (custom slots).
rem Usage: double-click, or: FLASH-custom.bat COM11
rem
rem NOTE: the prebuilt image is NOT shipped in git (it embeds artwork generated from
rem       the official Clawd-Mochi assets). Build it yourself:
rem         cd fw  ^&^&  pio run
rem       then copy .pio\build\clawdmochi\firmware.bin here as clawdmochi-custom.bin.
rem       Also: if the official control center is in "USB wired" mode it owns the COM
rem       port, so switch it back to Wi-Fi mode before flashing.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    pause
    exit /b 1
)

set PORT=%~1
if "%PORT%"=="" set PORT=COM11
set IMG=%~dp0clawdmochi-custom.bin
if not exist "%IMG%" (
    echo ERROR: %IMG% not found.
    echo Build it with:  cd fw  ^&^&  pio run
    echo Then copy .pio\build\clawdmochi\firmware.bin to this folder as clawdmochi-custom.bin
    pause
    exit /b 1
)

echo Flashing:  %IMG%
echo Target:    %PORT%  at 0x10000 (app only)
echo.
echo If this fails with "Could not open %PORT%", do ONE of these:
echo   * switch the Clawd-Mochi control center back to Wi-Fi mode
echo   * unplug and replug the Type-C cable, then run this again
echo   * hold BOOT, tap RST, release BOOT (download mode), then run again
echo.
python -m esptool --chip esp32c3 --port %PORT% --baud 460800 --after hard-reset write-flash 0x10000 "%IMG%"
echo.
echo Done. The device reconnects to WiFi in ~10 seconds.
pause
