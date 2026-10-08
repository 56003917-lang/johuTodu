@echo off
rem Safety Training Platform v0.1 launcher (Windows).
rem For production, host the python command below with NSSM.
rem NOTE: keep this file ASCII-only; cmd.exe may mis-split UTF-8 lines.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

rem Guard: venv interpreter must be 3.12/3.13 (tested); rebuild if mismatched.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo [ENV] venv python version mismatch, rebuilding...
    rmdir /s /q .venv
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [INIT] Creating venv and installing dependencies...
  py -3.13 -m venv .venv 2>nul || py -3.12 -m venv .venv 2>nul || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
)
".venv\Scripts\python.exe" run.py config.yaml
pause
