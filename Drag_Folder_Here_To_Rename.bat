@echo off
title Stock Image and Vector Auto-Renamer
setlocal EnableDelayedExpansion

set "TARGET_DIR=%~1"

:: Only prompt if no folder was dragged or passed from SendTo
if "%TARGET_DIR%"=="" (
    echo =======================================================
    echo    Stock Image and Vector Auto-Renamer (Gemini AI)
    echo =======================================================
    echo.
    set /p "TARGET_DIR=Paste or drag the folder path here: "
)

:: Strip surrounding quotes if present
set "TARGET_DIR=%TARGET_DIR:"=%"

if "%TARGET_DIR%"=="" (
    echo Error: No folder path provided.
    pause
    exit /b 1
)

echo.
echo Running renamer on: "%TARGET_DIR%"
echo.

py "%~dp0rename.py" "%TARGET_DIR%"

echo.
pause
