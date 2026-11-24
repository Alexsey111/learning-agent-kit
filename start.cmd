@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Аргумент: имя папки инстанса. Без аргумента — demo (потыкаться), иначе study, иначе study_example.
set STUDY=%~1
if "%STUDY%"=="" if exist "%~dp0demo" set STUDY=demo
if "%STUDY%"=="" if exist "%~dp0study" set STUDY=study
if "%STUDY%"=="" if exist "%~dp0study_example" set STUDY=study_example
if not exist "%~dp0%STUDY%" (
  echo Нет такой папки данных: %STUDY%
  echo Что есть рядом:
  for /d %%D in ("%~dp0*") do if exist "%%~D\current.txt" echo    %%~nxD
  pause
  exit /b 2
)
echo Инстанс: %STUDY%
if /i "%STUDY%"=="demo" echo Это демо: урок, блок и проверка без агента. Своя тема: start.cmd study
python "%~dp0trainer/trainer.py" --study "%~dp0%STUDY%"
if errorlevel 1 pause
