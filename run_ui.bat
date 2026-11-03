@echo off
cd /d %~dp0
rem Starts the web app and opens http://localhost:8000 (no Node.js needed: the built app is in web\dist)
python -m src.main web
