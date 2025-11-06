@echo off
:: Check for admin privileges
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo ⚠️ Admin privileges required. Relaunching as administrator...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

REM Navigate to Citadel project folder
cd /d C:\Citadel

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Run Main program
python main.py

REM Keep the command prompt open
cmd /k
