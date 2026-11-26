@echo off
rem Double-click to start hoyoTTS without a console window.
rem If hotkeys do not work while the game is focused: right-click -> Run as administrator.
cd /d "%~dp0"

set "ENV_PY="
for %%R in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3") do (
    if not defined ENV_PY if exist "%%~R\envs\hoyoTTS\pythonw.exe" set "ENV_PY=%%~R\envs\hoyoTTS"
)
if not defined ENV_PY (
    echo Conda env "hoyoTTS" not found. Please install it first, see README.
    pause
    exit /b 1
)

rem ffmpeg and other DLLs of the conda env live in Library\bin
set "PATH=%ENV_PY%;%ENV_PY%\Library\bin;%ENV_PY%\Scripts;%PATH%"
start "" "%ENV_PY%\pythonw.exe" main.py
