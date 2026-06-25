@echo off
title FaceID - Face Recognition App
color 0A

echo.
echo  ================================================
echo    FaceID - Face Recognition Student App
echo  ================================================
echo.
echo  Starting server...
echo  Browser will open automatically in 3 seconds.
echo.
echo  Press CTRL+C to stop the server.
echo  ================================================
echo.

cd /d "%~dp0"

:: Open browser after 3 second delay (runs in background)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"

call venv\Scripts\activate.bat
python app.py

pause
