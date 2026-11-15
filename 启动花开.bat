@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 "projects\flower_bloom\flower_app.py"
if errorlevel 1 pause
