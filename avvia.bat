@echo off
chcp 65001 >nul
title Alinea - generatore PC-DMIS
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
  echo Prima installazione: creo l ambiente Python in .venv ...
  %PY% -m venv .venv || goto :nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :piperr
)

".venv\Scripts\python.exe" -m alinea
pause
exit /b 0

:nopython
echo.
echo Python 3.10 o superiore non trovato.
echo Installalo da https://www.python.org/downloads/ spuntando "Add python.exe to PATH", poi rilancia avvia.bat
pause
exit /b 1

:piperr
echo.
echo Installazione delle librerie non riuscita: controlla la connessione a internet e rilancia avvia.bat
rmdir /s /q .venv
pause
exit /b 1
