@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ১. ব্যাকগ্রাউন্ডে প্রয়োজনীয় সব VPN CLI পাথ যুক্ত করা
set "PATH=%PATH%;C:\Program Files\Private Internet Access;C:\Program Files\PIA;C:\Program Files\ExpressVPN\services;C:\Program Files (x86)\ExpressVPN\services;C:\Program Files\NordVPN;%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python312;C:\Windows"

set "TARGET_SCRIPT=%~dp0Salman_Boss_VPN_Manager_v0_5_DirectDownload.py"

:: ২. পিসিতে থাকা Python Launcher (py / python) স্বয়ংক্রিয়ভাবে শনাক্ত করা
set "PY_CMD="
where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py"
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    )
)

if "%PY_CMD%"=="" (
    echo Python is not installed or not in PATH. Please install Python 3.11+ first.
    pause
    exit /b 1
)

:: ৩. PySide6 না থাকলে প্রথমবার স্বয়ংক্রিয়ভাবে ইনস্টল করে নেওয়া
%PY_CMD% -c "import PySide6" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing required GUI libraries in background, please wait...
    %PY_CMD% -m pip install --upgrade pip --quiet
    %PY_CMD% -m pip install "PySide6>=6.7,<7" --quiet
)

:: ৪. ডাবল-ক্লিক করলেই সরাসরি অ্যাপ চালু হওয়া (Python নিজে থেকেই কালো CMD উইন্ডো লুকিয়ে ফেলবে)
start "" %PY_CMD% "%TARGET_SCRIPT%"
exit /b 0