@echo off
rem 安全生产在线培训平台 v0.1 启动脚本（Windows；生产环境建议用 NSSM 托管本脚本内的启动命令）
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [首次初始化] 创建虚拟环境并安装依赖...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
)
".venv\Scripts\python.exe" run.py config.yaml
pause
