@echo off
rem Stop the Clawd-Mochi x CS2 kill-reaction bridge.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*cs2_mochi.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('[i] stopped pid ' + $_.ProcessId) }"
