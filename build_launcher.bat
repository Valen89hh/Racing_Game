@echo off
echo ========================================
echo   Building Launcher (onefile)
echo ========================================

:: Activate venv if present
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

pyinstaller launcher.spec --noconfirm --clean

if %ERRORLEVEL% neq 0 (
    echo BUILD FAILED!
    pause
    exit /b 1
)

echo.
echo Launcher built successfully: dist\launcher.exe
pause
