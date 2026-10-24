@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title ABC2027 - Cong Cu Tinh Chinh Ground Truth v4 (IMG_0114 ^& IMG_0115)

echo ============================================================================
echo   ABC2027 TrackID3x3 - Cong Cu Tinh Chinh Ground Truth (Solver v4)
echo   Tu dong khoi chay tren moi may tinh Windows
echo ============================================================================
echo.

set "PY_EXE="

:: 1. Thu tim Python trong Conda / Miniconda / Anaconda / LocalAppData
for %%P in (
    "%USERPROFILE%\miniconda3\envs\hokkaido_env\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
) do (
    if exist %%P (
        set "PY_EXE=%%~P"
        goto :FOUND_PY
    )
)

:: 2. Thu tim trong LocalAppData\Programs\Python
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        set "PY_EXE=%%D\python.exe"
        goto :FOUND_PY
    )
)

:: 3. Thu py launcher hoac python trong PATH (bo qua WindowsApps stub)
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY_EXE=py"
    goto :FOUND_PY
)

for /f "delims=" %%I in ('where python 2^>nul') do (
    echo "%%I" | findstr /i "WindowsApps" >nul
    if !ERRORLEVEL! NEQ 0 (
        set "PY_EXE=%%I"
        goto :FOUND_PY
    )
)

echo [LOI] Khong tim thay Python tren may! Vui long cai dat Python 3.9+ hoac Miniconda.
pause
exit /b 1

:FOUND_PY
echo [1/3] Da tim thay Python: "!PY_EXE!"

echo [2/3] Kiem tra thu vien (opencv-python, numpy, pandas)...
"!PY_EXE!" -c "import cv2, numpy, pandas" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo       Dang tu dong cai dat thu vien can thiet...
    "!PY_EXE!" -m pip install opencv-python numpy pandas -q
)

echo [3/3] Dang mo giao dien Web chinh sua Ground Truth...
echo       Sau khi chinh sua xong, nhan Ctrl+S va gui lai cac file trong thu muc:
echo       "%~dp0output_ground_truth\"
echo.
"!PY_EXE!" -X utf8 "%~dp0gt_editor_standalone.py"
pause
