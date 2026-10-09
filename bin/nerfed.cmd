@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0nerfed.ps1" %*
exit /b %errorlevel%
