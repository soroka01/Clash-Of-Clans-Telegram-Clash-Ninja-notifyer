@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"

rem Update only tracked project files. config.json and data/ are ignored by Git.
where git >nul 2>&1
if errorlevel 1 (
    echo [UPDATE] Git was not found. Starting the installed version.
) else if not exist ".git" (
    echo [UPDATE] This folder is not a Git repository. Starting the installed version.
) else (
    set "HAS_LOCAL_CHANGES="
    for /f "delims=" %%A in ('git status --porcelain') do set "HAS_LOCAL_CHANGES=1"
    if defined HAS_LOCAL_CHANGES (
        echo [UPDATE] Local tracked changes found. Update skipped to keep them safe.
    ) else (
        echo [UPDATE] Checking GitHub for updates...
        git fetch origin main
        if errorlevel 1 (
            echo [UPDATE] Could not contact GitHub. Starting the installed version.
        ) else (
            git diff --quiet HEAD origin/main
            if errorlevel 1 (
                echo [UPDATE] Installing the latest version...
                git pull --ff-only origin main
                if errorlevel 1 echo [UPDATE] Update failed. Starting the installed version.
            ) else (
                echo [UPDATE] The bot is already up to date.
            )
        )
    )
)

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
