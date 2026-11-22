@echo off
setlocal
rem FULL factory restore: writes a WHOLE 4 MB flash backup from 0x0.
rem ERASES WiFi credentials and all custom slots.
rem Usage: double-click, or: RESTORE-factory-full.bat COM11
rem
rem You must provide your own full backup of the device (factory firmware installed):
rem   python -m esptool --chip esp32c3 --port COM11 --baud 460800 read-flash 0x0 0x400000 full.bin
rem then put full.bin in this folder as  factory-full-backup.bin
rem The factory firmware is third-party copyrighted code and is NOT shipped here.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    pause
    exit /b 1
)

set PORT=%~1
if "%PORT%"=="" set PORT=COM11
set IMG=%~dp0factory-full-backup.bin
if not exist "%IMG%" (
    echo ERROR: %IMG% not found.
    echo Put your own 4 MB flash backup there first (see the rem notes in this file).
    pause
    exit /b 1
)

echo WARNING: this erases WiFi settings and all custom slots on the device.
echo Target: %PORT%   image: %IMG%
choice /c YN /m "Continue"
if errorlevel 2 exit /b 1

python -m esptool --chip esp32c3 --port %PORT% --baud 460800 --after hard-reset write-flash 0x0 "%IMG%"
echo.
echo Done. The device is back to the factory state and will ask for WiFi again.
pause
