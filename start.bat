@echo off
title FaceID - Face Recognition App
color 0A

echo.
echo  ================================================
echo    FaceID - Face Recognition Student App
echo  ================================================
echo.

cd /d "%~dp0"

:: Kill any old server running on port 5000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000 " ^| findstr "LISTENING" 2^>nul') do (
    echo  Stopping old server process PID %%a ...
    taskkill /PID %%a /F >nul 2>&1
)

echo  Starting server...
echo  Browser will open automatically in 4 seconds.
echo.
echo  Press CTRL+C to stop the server.
echo  ================================================
echo.

:: Open browser after 4 seconds (background)
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:5000/admin/persons"

:: Use venv Python EXPLICITLY - never system Python
"%~dp0venv\Scripts\python.exe" "%~dp0app.py"

pause
