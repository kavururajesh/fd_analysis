@echo off
cd /d %~dp0..
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
copy /y .env.example .env
echo Done. Edit .env (GigaChat URL / certificate paths), then run run_ui.bat
