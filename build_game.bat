@echo off
echo ========================================
echo   Building Game (onedir)
echo ========================================

:: Activate venv if present
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

pyinstaller game.spec --noconfirm --clean

if %ERRORLEVEL% neq 0 (
    echo BUILD FAILED!
    pause
    exit /b 1
)

echo.
echo Game built successfully: dist\game\
pause
