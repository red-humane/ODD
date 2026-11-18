@echo off
if exist "%~dp0Uninstall ODD.exe" (
    start "" "%~dp0Uninstall ODD.exe" --uninstall
    exit /b
)
if exist "%~dp0ODD_Setup.exe" (
    start "" "%~dp0ODD_Setup.exe" --uninstall
    exit /b
)
powershell -NoProfile -Command "Get-Process -Name 'ODD' -ErrorAction SilentlyContinue | Stop-Process -Force"
del /Q "%USERPROFILE%\Desktop\ODD.lnk" 2>nul
del /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ODD.lnk" 2>nul
del /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Uninstall ODD.lnk" 2>nul
del /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ODD.lnk" 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ODD" /f 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ODD" /f 2>nul
cd %TEMP%
rmdir /S /Q "E:\Project\Odd" 2>nul
echo ODD has been uninstalled successfully.
