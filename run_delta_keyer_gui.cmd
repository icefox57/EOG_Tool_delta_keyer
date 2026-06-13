@echo off
setlocal
set "PY=C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PY%" (
  "%PY%" "%~dp0delta_keyer.py" --gui
) else (
  python "%~dp0delta_keyer.py" --gui
)
