@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title "N.E.X.U.S. - Neural Experience & Unified System"

:: If standalone compiled executable exists, run it directly (no Python needed)
if exist "%~dp0NEXUS.exe" (
    echo Starting N.E.X.U.S. standalone executable...
    "%~dp0NEXUS.exe" %*
    goto :handle_exit
)
if exist "%~dp0dist\NEXUS.exe" (
    echo Starting N.E.X.U.S. standalone executable from dist...
    "%~dp0dist\NEXUS.exe" %*
    goto :handle_exit
)

echo Starting N.E.X.U.S. in virtual environment...

:: Resolve virtual environment root directory across standard, subfolder, and backup locations
set "VENV_ROOT="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "VENV_ROOT=%~dp0.venv"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "VENV_ROOT=%~dp0..\.venv"
) else if exist "D:\hologram\.venv\Scripts\python.exe" (
    set "VENV_ROOT=D:\hologram\.venv"
)

:: Configure verified PySide6 Qt platform plugin paths and DLL search directory
if defined VENV_ROOT (
    set "PYSIDE6_DIR=!VENV_ROOT!\Lib\site-packages\PySide6"
    set "SHIBOKEN6_DIR=!VENV_ROOT!\Lib\site-packages\shiboken6"
    set "VENV_PY=!VENV_ROOT!\Scripts\python.exe"
    if exist "!VENV_ROOT!\Scripts\activate.bat" (
        call "!VENV_ROOT!\Scripts\activate.bat"
    )
    if exist "!PYSIDE6_DIR!\plugins\platforms" (
        set "PATH=!PYSIDE6_DIR!;!SHIBOKEN6_DIR!;!PATH!"
        set "QT_PLUGIN_PATH=!PYSIDE6_DIR!\plugins"
        set "QT_QPA_PLATFORM_PLUGIN_PATH=!PYSIDE6_DIR!\plugins\platforms"
    )
    "!VENV_PY!" "%~dp0main.py" %*
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%~dp0main.py" %*
) else (
    py -3 "%~dp0main.py" %* || python "%~dp0main.py" %*
)

:handle_exit
if errorlevel 1 (
    echo.
    echo Application stopped with an exit code: %errorlevel%
    pause
)
