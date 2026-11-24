@echo off
cd /d "%~dp0"
python trainer\trainer.py --study "%~dp0study"
if errorlevel 1 pause
