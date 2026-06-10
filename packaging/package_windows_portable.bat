@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "RELEASE_ROOT=%PROJECT_ROOT%\release"
set "APP_DIR=%RELEASE_ROOT%\DNGauge-windows-portable"
set "ARCHIVE_PATH=%RELEASE_ROOT%\DNGauge-windows-portable.zip"

if not exist "%RELEASE_ROOT%" mkdir "%RELEASE_ROOT%"
if exist "%APP_DIR%" rmdir /s /q "%APP_DIR%"
mkdir "%APP_DIR%"

copy "%PROJECT_ROOT%\dist\DNGauge.exe" "%APP_DIR%\DNGauge.exe" >nul
copy "%SCRIPT_DIR%DNGauge.ico" "%APP_DIR%\DNGauge.ico" >nul
copy "%SCRIPT_DIR%\portable_assets\README_RUN_WINDOWS.txt" "%APP_DIR%\README_RUN.txt" >nul
copy "%SCRIPT_DIR%\portable_assets\README_RUN_WINDOWS_CN.txt" "%APP_DIR%\README_RUN_CN.txt" >nul
copy "%SCRIPT_DIR%\portable_assets\README_RUN_WINDOWS_EN.txt" "%APP_DIR%\README_RUN_EN.txt" >nul

if exist "%ARCHIVE_PATH%" del /f /q "%ARCHIVE_PATH%"
powershell -NoProfile -Command "Compress-Archive -Path '%APP_DIR%\*' -DestinationPath '%ARCHIVE_PATH%'"

echo.
echo Portable folder created:
echo   %APP_DIR%
echo.
echo Portable archive created:
echo   %ARCHIVE_PATH%

endlocal
