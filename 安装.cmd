@echo off
cd /d "%~dp0"
py -3 scripts\launch_installer.py
if errorlevel 1 pause
