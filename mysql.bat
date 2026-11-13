@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage:
  echo   mysql.bat start
  echo   mysql.bat status
  echo   mysql.bat logs
  echo   mysql.bat stop
  echo   mysql.bat connection
  echo   mysql.bat backup
  echo   mysql.bat restore
  exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mysql.ps1" %*
if errorlevel 1 (
  echo.
  echo MySQL operation failed. Review the error above.
  exit /b 1
)
