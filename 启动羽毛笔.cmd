@echo off
rem ---------------------------------------------------------------
rem 2026-11-21: this file used to be UTF-8 and hard-coded the Chinese
rem   name of the boot script. A double-click runs cmd.exe under the
rem   system ANSI codepage (936 here), so the UTF-8 bytes turned into
rem   garbage, powershell received a path that does not exist, the
rem   console closed at once and the user only saw "nothing happens".
rem   The GBK-encoded .bat sibling kept working for the same reason.
rem   Fix: keep this file pure ASCII and resolve the boot script by
rem   wildcard, so no codepage can break it. Console stays visible,
rem   so if startup ever fails again the reason is on screen.
rem ---------------------------------------------------------------
cd /d "%~dp0"
set "BOOT="
for %%f in ("*.ps1") do if not defined BOOT set "BOOT=%%~ff"
if not defined BOOT (
    echo [ERROR] No .ps1 boot script next to this launcher.
    echo         Look in: %~dp0
    pause
    exit /b 2
)
rem 2026-11-21 user: no console window wanted (see screenshot 2). The boot script still logs every
rem   step to %USERPROFILE%\.pluma\logs\launcher.log and pops a dialog if startup fails,
rem   so hiding the console does not hide the reason any more.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%BOOT%" -Windowed %*
