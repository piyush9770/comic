@echo off
title AI Motion Comic & Video Studio
color 0A

echo ====================================================================
echo             STARTING AI STORY & VIDEO STUDIO WEB APP
echo ====================================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"
) else (
    set PYTHON_EXE=python
)

echo Using Python: %PYTHON_EXE%
echo Launching Studio Web Server on http://127.0.0.1:5000...
echo.

start "" "http://127.0.0.1:5000"

%PYTHON_EXE% "%~dp0studio\app.py"

pause
