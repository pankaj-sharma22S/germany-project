@echo off
title Facial Attendance System - Web UI
echo ========================================================
echo  Starting Facial Attendance System Web UI...
echo ========================================================
python run_web_ui.py
if errorlevel 1 (
    echo.
    echo Server stopped or error encountered.
    pause
)
