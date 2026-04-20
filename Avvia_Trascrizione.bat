@echo off
cd /d "%~dp0"
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Errore durante l'avvio. Premi un tasto per chiudere.
    pause >nul
)
