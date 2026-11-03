@echo off
cd /d %~dp0
python -m src.main refresh > logs\last_refresh.txt 2>&1
exit /b %errorlevel%
