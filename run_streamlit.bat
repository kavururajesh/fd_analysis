@echo off
cd /d %~dp0
rem Previous Streamlit interface (kept as a fallback)
python -m src.main ui
