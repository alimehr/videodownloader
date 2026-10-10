@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
if errorlevel 1 (
 echo.
 echo Installation did not complete. Read the message above, then run Install again.
 pause
)
