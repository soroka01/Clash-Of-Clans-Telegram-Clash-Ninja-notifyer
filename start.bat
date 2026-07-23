@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"

set "PYTHON_CMD=.venv\Scripts\python.exe"
if not exist "%PYTHON_CMD%" (
    set "BOOTSTRAP_PY="
    where py >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PY=py -3.14"
    if not defined BOOTSTRAP_PY (
        where python >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PY=python"
    )
    if not defined BOOTSTRAP_PY (
        echo [ERROR] Python 3.14 or newer was not found.
        exit /b 1
    )
    echo [SETUP] Creating .venv in the current directory...
    %BOOTSTRAP_PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create .venv.
        exit /b 1
    )
)

echo [SETUP] Updating pip, setuptools and wheel in .venv...
"%PYTHON_CMD%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERROR] Could not update Python tools in .venv.
    exit /b 1
)

echo [SETUP] Installing project dependencies into .venv...
"%PYTHON_CMD%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
)

"%PYTHON_CMD%" main.py %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
