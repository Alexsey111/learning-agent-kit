@echo off
chcp 65001 >nul
cd /d "%~dp0"
set STUDY=%~1
if "%STUDY%"=="" set STUDY=study_tensors
if not exist "%~dp0%STUDY%" (
  echo Нет такой папки данных: %STUDY%
  echo Запуск: start.cmd study_example
  echo Что есть рядом:
  for /d %%D in ("%~dp0study*") do echo    %%~nxD
  pause
  exit /b 2
)
python "%~dp0trainer\trainer.py" --study "%~dp0%STUDY%"
if errorlevel 1 pause
