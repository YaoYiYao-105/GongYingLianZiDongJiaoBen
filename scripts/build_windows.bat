@echo off
setlocal

echo ============================================
echo  Building the Windows executable
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on PATH.
  echo         Install it from https://www.python.org/downloads/windows/
  echo         and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

echo [1/4] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller pytest
if errorlevel 1 goto failed

echo.
echo [2/4] Running tests...
python -m pytest tests -q
if errorlevel 1 goto failed

echo.
echo [3/4] Building the executable...
python -m PyInstaller --noconfirm --windowed --name supplier-portal-automation --collect-all playwright app.py
if errorlevel 1 goto failed

echo.
echo [4/4] Done.
echo.
echo Output: dist\supplier-portal-automation\supplier-portal-automation.exe
echo Zip that folder and send it to your colleagues.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] Build failed. Read the messages above.
pause
exit /b 1
