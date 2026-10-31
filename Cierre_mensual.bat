@echo off
REM Cierre mensual con doble clic: pregunta cliente y mes.
cd /d "%~dp0"
chcp 65001 >nul
set /p CLIENTE=Cliente (nombre de la carpeta, o TODOS): 
set /p MES=Mes a cerrar (AAAA-MM, por ejemplo 2026-11): 
if /I "%CLIENTE%"=="TODOS" (
  python cierre.py --todos --mes %MES%
) else (
  python cierre.py --cliente %CLIENTE% --mes %MES%
)
pause
