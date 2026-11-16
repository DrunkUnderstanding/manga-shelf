@echo off
rem One-click launcher: run app.py from source without a console window.
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0app.py"
) else (
    start "" python "%~dp0app.py"
)
