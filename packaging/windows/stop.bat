@echo off
cd /d "%~dp0"
echo Stopping PostgreSQL...
"%~dp0pgsql\bin\pg_ctl.exe" -D "%~dp0data" -m fast stop
echo.
echo If the API window is still open, close it.
pause
