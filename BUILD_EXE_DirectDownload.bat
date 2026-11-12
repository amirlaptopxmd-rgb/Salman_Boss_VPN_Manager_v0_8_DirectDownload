@echo off
setlocal
cd /d "%~dp0"
py -m pip install --upgrade pip
py -m pip install PySide6 pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name SalmanBossVPNManager "%~dp0Salman_Boss_VPN_Manager_v0_5_DirectDownload.py"
echo.
echo Portable EXE Ready: dist\SalmanBossVPNManager.exe
pause