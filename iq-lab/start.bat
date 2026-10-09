@echo off
REM One command: install, test, backtest, then run the engine + dashboard.
REM Usage: start.bat "https://script.google.com/macros/s/XXXX/exec"
cd /d %~dp0
if not "%~1"=="" set IQLAB_SHEETS_WEBHOOK=%~1
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt || exit /b 1
python -m pytest -q tests || exit /b 1
python -m iqlab backtest --session-only
echo Dashboard: http://localhost:8765  ^|  next: open Claude in this folder and type: start trading session
start http://localhost:8765
python -m iqlab run
