@echo off
rem =========================================================
rem  Clawd-Mochi  x  CS2  kill-reaction bridge  (launcher)
rem  Runs hidden in background (pythonw, no console window).
rem  Any arguments are passed through to cs2_mochi.py, e.g.:
rem     start.bat --anim error
rem     start.bat --text --text-min-tier 2
rem =========================================================
setlocal
set "HERE=%~dp0"
set "SCRIPT=%HERE%..\cs2_mochi.py"
rem pythonw from PATH (no console window). If yours is elsewhere, set the full path.
set "PYW=pythonw"
set "CURL=%SystemRoot%\System32\curl.exe"

if not exist "%SCRIPT%" goto noscript
where pythonw >nul 2>nul
if errorlevel 1 goto nopy

rem already running?  (health endpoint answers 200 -> curl exit 0)
"%CURL%" -s -m 2 -o nul http://127.0.0.1:18895/health
if not errorlevel 1 (
  echo [i] Already running. Open http://127.0.0.1:18895/status
  ping -n 3 127.0.0.1 >nul
  exit /b 0
)

start "" /b pythonw "%SCRIPT%" --slots --anim-map "1=done,2=coding,3=waiting,4=thinking,5=error" %* >nul 2>nul
echo [i] Started. Health: http://127.0.0.1:18895/health
ping -n 2 127.0.0.1 >nul
exit /b 0

:nopy
echo [x] pythonw not found in PATH.
echo     Install Python 3 (with "Add to PATH") or set PYW to the full pythonw.exe path above.
pause
exit /b 1

:noscript
echo [x] Script not found: %SCRIPT%
pause
exit /b 1
