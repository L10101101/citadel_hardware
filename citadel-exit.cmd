@echo off
:: ADMIN
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo ⚠️ Admin privileges required. Relaunching as administrator...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

REM FOLDER
cd /d C:\Citadel

REM VENV
call venv\Scripts\activate.bat

REM MAIN
python exit_window.py

REM KEEP
cmd /k
