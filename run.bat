@echo off
REM Jalankan Computer Controller: hand gesture + voice command (klik 2x).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtualenv belum ada. Jalankan perintah instalasi dari README.md dulu.
    pause
    exit /b 1
)
if not exist "assets\hand_landmarker.task" (
    echo [ERROR] Model assets\hand_landmarker.task tidak ditemukan.
    echo Lihat langkah instalasi model di README.md.
    pause
    exit /b 1
)
set MPLCONFIGDIR=%~dp0.tmp\mpl
if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"
".venv\Scripts\python.exe" main.py
pause
