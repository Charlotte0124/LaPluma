@echo off
cd /d "%~dp0"
set "PYW=C:\Users\Charlotte\AppData\Local\Programs\Python\Python312\pythonw.exe"
if exist "%PYW%" goto run
set "PYW="
for /f "delims=" %%p in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%p"
if not defined PYW (
  echo Cannot find pythonw.exe. Install Python 3.12 with Add python.exe to PATH.
  pause
  exit /b 2
)
:run
start "" "%PYW%" "ui\server.py"
