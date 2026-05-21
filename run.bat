@echo off
setlocal

REM DNG_COMPARE 启动脚本（Windows）
REM 用法:
REM   run.bat
REM   run.bat left.dng right.dng

set "SCRIPT_DIR=%~dp0"
set "CONDA_BASE=%USERPROFILE%\miniconda3"
if not exist "%CONDA_BASE%\Scripts\activate.bat" (
    set "CONDA_BASE=%USERPROFILE%\anaconda3"
)

if not exist "%CONDA_BASE%\Scripts\activate.bat" (
    echo [ERROR] Cannot find conda activate script.
    echo Please edit run.bat and set CONDA_BASE manually.
    exit /b 1
)

call "%CONDA_BASE%\Scripts\activate.bat" dng_compare
if errorlevel 1 (
    echo [ERROR] Failed to activate conda env: dng_compare
    exit /b 1
)

cd /d "%SCRIPT_DIR%"
python shotwell_compare.py %*

endlocal
