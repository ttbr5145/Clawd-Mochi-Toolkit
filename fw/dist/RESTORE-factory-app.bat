@echo off
setlocal
rem Restore the ORIGINAL factory app image (keeps WiFi credentials and LittleFS slots).
rem Usage: double-click, or: RESTORE-factory-app.bat COM11
rem
rem You must provide your own backup of the factory app partition:
rem   put it in this folder as  clawdmochi-stock-app.bin   (written at 0x10000)
rem The factory firmware itself is third-party copyrighted code and is NOT shipped here.
rem How to make the backup while the factory firmware is still installed:
rem   python -m esptool --chip esp32c3 --port COM11 --baud 460800 read-flash 0x0 0x400000 full.bin
rem   (then extract 0x10000..0x310000 into clawdmochi-stock-app.bin, or just keep full.bin
rem    and use RESTORE-factory-full.bat)

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    pause
    exit /b 1
)

set PORT=%~1
if "%PORT%"=="" set PORT=COM11
set IMG=%~dp0clawdmochi-stock-app.bin
if not exist "%IMG%" (
    echo ERROR: %IMG% not found.
    echo Put your own factory-app backup there first (see the rem notes in this file).
    pause
    exit /b 1
)

echo Restoring factory app image to %PORT% at 0x10000 ...
python -m esptool --chip esp32c3 --port %PORT% --baud 460800 --after hard-reset write-flash 0x10000 "%IMG%"
echo.
echo Done. Back to the factory firmware (custom slots remain in LittleFS but are ignored).
pause
