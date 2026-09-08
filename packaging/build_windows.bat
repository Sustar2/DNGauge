@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"

cd /d "%PROJECT_ROOT%"

python "%SCRIPT_DIR%check_plain_raw_pipeline.py"
if errorlevel 1 (
    echo.
    echo ERROR: Required dependencies or the plain RAW pipeline are unavailable.
    echo Run: python -m pip install -r requirements.txt
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller --noconfirm --distpath "%PROJECT_ROOT%\dist" --workpath "%PROJECT_ROOT%\build" "%SCRIPT_DIR%DNGauge.spec"
if errorlevel 1 (
    echo.
    echo ERROR: Windows build failed.
    exit /b 1
)

if not exist "%PROJECT_ROOT%\dist\DNGauge.exe" (
    echo.
    echo ERROR: DNGauge.exe was not created.
    exit /b 1
)

echo.
echo Windows executable created:
echo   %PROJECT_ROOT%\dist\DNGauge.exe

endlocal
