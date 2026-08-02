@echo off
setlocal
if exist scripts\repository-update.ps1 powershell -NoProfile -File scripts\repository-update.ps1 -Auto
if not exist venv (
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)
python -m pip install -r requirements.txt
python -m app.main
