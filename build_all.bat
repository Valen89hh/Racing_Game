@echo off
echo ========================================
echo   Arcade Racing 2D - Full Build
echo ========================================
echo.

:: Activate venv if present
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: Step 1: Install dependencies
echo [1/5] Installing dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo FAILED to install dependencies!
    pause
    exit /b 1
)

:: Step 2: Build game
echo.
echo [2/5] Building game (onedir)...
pyinstaller game.spec --noconfirm --clean
if %ERRORLEVEL% neq 0 (
    echo FAILED to build game!
    pause
    exit /b 1
)

:: Step 3: Build launcher
echo.
echo [3/5] Building launcher (onefile)...
pyinstaller launcher.spec --noconfirm --clean
if %ERRORLEVEL% neq 0 (
    echo FAILED to build launcher!
    pause
    exit /b 1
)

:: Step 4: Assemble release
echo.
echo [4/5] Assembling release...

:: Clean previous release
if exist "dist\release" rmdir /s /q "dist\release"
mkdir "dist\release"

:: Copy launcher.exe
copy "dist\launcher.exe" "dist\release\launcher.exe" >nul

:: Copy game folder
xcopy "dist\game" "dist\release\game\" /e /i /q >nul

:: Copy version.txt and config.json
copy "version.txt" "dist\release\version.txt" >nul
copy "config.json" "dist\release\config.json" >nul

:: Step 5: Show result
echo.
echo [5/5] Build complete!
echo.
echo ========================================
echo   dist\release\
echo   +-- launcher.exe
echo   +-- version.txt
echo   +-- config.json
echo   +-- game\
echo       +-- game.exe
echo       +-- assets\
echo       +-- tracks\
echo       +-- brushes\
echo ========================================
echo.
echo Ready to distribute!
pause
