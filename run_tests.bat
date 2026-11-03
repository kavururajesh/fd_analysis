@echo off
cd /d %~dp0
python -m pytest
python -m evals.evaluate_agent
pause
