@echo off
set "PORT=%~1"
for /l %%i in (1,1,60) do (
  curl.exe -s -f -o nul "http://127.0.0.1:%PORT%/api/health" && goto :open
  ping -n 2 127.0.0.1 >nul
)
exit /b 1

:open
start "" "http://localhost:%PORT%"
exit /b 0
