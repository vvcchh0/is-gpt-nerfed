@echo off
if not exist "%~dp0IsGPTNerfed.exe" goto source
if "%~1"=="" goto detached
:checkLegacy
if "%~1"=="--legacy-tk" goto source
if "%~1"=="" goto compiled
shift /1
goto checkLegacy
:compiled
"%~dp0IsGPTNerfed.exe" %*
exit /b %errorlevel%
:detached
start "" "%~dp0IsGPTNerfed.exe"
exit /b %errorlevel%
:source
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
exit /b %errorlevel%
