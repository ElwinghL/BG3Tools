@echo off
REM Lance le TUI BG3 Mod Tools sur Windows.
REM Cree un environnement virtuel local (.venv) si necessaire, installe les
REM dependances, puis demarre le TUI. L'elevation de privileges (UAC) n'est
REM demandee par l'application elle-meme que si elle s'avere necessaire
REM (creation des liens symboliques/hardlinks).

setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "VENV_DIR=%SCRIPT_DIR%.venv"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_LAUNCHER=py"
) else (
    set "PY_LAUNCHER=python"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creation de l'environnement virtuel ^(.venv^)...
    %PY_LAUNCHER% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Erreur : impossible de creer l'environnement virtuel. Python est-il installe ?
        exit /b 1
    )
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

"%VENV_PYTHON%" -m pip install -q --upgrade pip
"%VENV_PYTHON%" -m pip install -q -e .
if errorlevel 1 (
    echo Erreur lors de l'installation des dependances.
    exit /b 1
)

"%VENV_PYTHON%" -m bg3_mod_tui %*

endlocal
