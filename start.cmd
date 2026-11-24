@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Аргумент: имя папки-инстанса. Без аргумента берём study, если он есть, иначе study_example.
set STUDY=%~1
if "%STUDY%"=="" if exist "%~dp0study" set STUDY=study
if "%STUDY%"=="" if exist "%~dp0study_example" set STUDY=study_example
if not exist "%~dp0%STUDY%" (
  echo Нет такой папки данных: %STUDY%
  echo Что есть рядом:
  for /d %%D in ("%~dp0study*") do echo    %%~nxD
  pause
  exit /b 2
)
echo Инстанс: %STUDY%
python "%~dp0trainer/trainer.py" --study "%~dp0%STUDY%"
if errorlevel 1 pause
