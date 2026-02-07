@echo off
REM Citadel Setup Wizard - run to configure or re-configure Citadel
cd /d C:\Citadel
call venv\Scripts\activate.bat
python setup_wizard.py
pause
