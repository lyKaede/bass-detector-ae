@echo off
REM ============================================================
REM  BassDetector - Build the standalone Windows executable (.exe)
REM  Double-click this file on Windows to create the exe.
REM  Requires: Python 3.9+ installed (with "Add to PATH").
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo Looking for an installed Python...

set "PY="

REM 1) Try the "py" launcher (most reliable on Windows)
py -3 --version >nul 2>&1
if not errorlevel 1 (
  set "PY=py -3"
  goto :found
)

REM 2) Try "python" - but skip the fake Microsoft Store stub
for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo !PYVER! | find /i "was not found" >nul
if errorlevel 1 (
  echo !PYVER! | find /i "Python" >nul
  if not errorlevel 1 (
    set "PY=python"
    goto :found
  )
)

echo.
echo ============================================================
echo   PYTHON NOT FOUND
echo ============================================================
echo.
echo Install Python once:
echo   1. Go to:  https://www.python.org/downloads/
echo   2. Run the installer and TICK "Add python.exe to PATH".
echo   3. Close this window and run build.bat again.
echo.
pause
exit /b 1

:found
echo Found: %PY%
%PY% --version

echo.
echo [1/3] Installing dependencies...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: dependency installation failed. Check your internet connection.
  pause
  exit /b 1
)

echo.
echo Closing any running instance and cleaning previous build...
taskkill /IM BassDetector.exe /F >nul 2>&1
ping -n 2 127.0.0.1 >nul
if exist "dist\BassDetector.exe" del /F /Q "dist\BassDetector.exe" >nul 2>&1
if exist "build" rmdir /S /Q "build" >nul 2>&1
if exist "BassDetector.spec" del /F /Q "BassDetector.spec" >nul 2>&1

if exist "dist\BassDetector.exe" (
  echo.
  echo WARNING: cannot remove the old dist\BassDetector.exe.
  echo It is probably still OPEN. Close BassDetector and run build.bat again.
  pause
  exit /b 1
)

echo.
echo [2/3] Building the executable with PyInstaller...
%PY% -m PyInstaller --noconfirm --onefile --windowed ^
  --name BassDetector ^
  --collect-all imageio_ffmpeg ^
  --collect-all tkinterdnd2 ^
  --collect-submodules scipy ^
  --hidden-import scipy._lib.messagestream ^
  bass_detector.py
if errorlevel 1 (
  echo.
  echo ERROR: build failed. Check the messages above.
  pause
  exit /b 1
)

echo.
echo [3/3] Done!
echo The executable is at:  dist\BassDetector.exe
echo.
pause
endlocal
