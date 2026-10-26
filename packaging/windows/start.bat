@echo off
setlocal
cd /d "%~dp0"

set "PGBIN=%~dp0pgsql\bin"
set "PGDATA=%~dp0data"

echo ==========================================
echo  Casino Admin - local demo
echo ==========================================

if not exist "%PGBIN%\pg_ctl.exe" (
  echo [ERROR] pgsql\bin\pg_ctl.exe not found. Is the zip fully extracted?
  goto :fail
)
if not exist "%~dp0python\python.exe" (
  echo [ERROR] python\python.exe not found. Is the zip fully extracted?
  goto :fail
)
if not exist "%~dp0find_free_port.ps1" (
  echo [ERROR] find_free_port.ps1 not found. Is the zip fully extracted?
  goto :fail
)

REM Select local ports without interfering with PostgreSQL or API services already on the PC.
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_free_port.ps1" -StartPort 55432 -EndPort 55532`) do set "PGPORT=%%P"
if not defined PGPORT (
  echo [ERROR] No free local PostgreSQL port found between 55432 and 55532.
  goto :fail
)
for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_free_port.ps1" -StartPort 8000 -EndPort 8099`) do set "API_PORT=%%P"
if not defined API_PORT (
  echo [ERROR] No free local API port found between 8000 and 8099.
  goto :fail
)
echo Using PostgreSQL port %PGPORT% and API port %API_PORT%.

REM --- 1. Create the database cluster (first run only) ---
if not exist "%PGDATA%\PG_VERSION" (
  echo [1/4] First run: initializing database cluster...
  "%PGBIN%\initdb.exe" -D "%PGDATA%" -U postgres -A trust -E UTF8 --locale=C >"%~dp0initdb.log" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [1/4] Database cluster found.
)

REM --- 2. Start PostgreSQL (skip if it is already running) ---
"%PGBIN%\pg_ctl.exe" -D "%PGDATA%" status >nul 2>&1
if errorlevel 1 (
  echo [2/4] Starting PostgreSQL on 127.0.0.1:%PGPORT% ...
  "%PGBIN%\pg_ctl.exe" -D "%PGDATA%" -l "%~dp0postgres.log" -o "-p %PGPORT% -c listen_addresses=127.0.0.1" -w start >nul 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [2/4] PostgreSQL already running.
)

REM --- 3. Load the seed (first successful run only; retries start from a clean database) ---
if not exist "%PGDATA%\.seed_done" (
  echo [3/4] Loading seed data...
  "%PGBIN%\dropdb.exe" -h 127.0.0.1 -p %PGPORT% -U postgres --if-exists casino >nul 2>&1
  "%PGBIN%\createdb.exe" -h 127.0.0.1 -p %PGPORT% -U postgres casino
  if errorlevel 1 goto :fail
  if exist "%~dp0seed\casino_demo.sql" (
    "%PGBIN%\psql.exe" -h 127.0.0.1 -p %PGPORT% -U postgres -d casino -q -v ON_ERROR_STOP=1 -f "%~dp0seed\casino_demo.sql" >"%~dp0seed.log" 2>&1
    if errorlevel 1 goto :fail
  )
  echo done> "%PGDATA%\.seed_done"
) else (
  echo [3/4] Seed data already loaded.
)

REM --- 4. Apply the auth-schema upgrade (safe to rerun on an existing demo database) ---
echo [4/5] Preparing administrator usernames...
"%PGBIN%\psql.exe" -h 127.0.0.1 -p %PGPORT% -U postgres -d casino -q -v ON_ERROR_STOP=1 -f "%~dp0seed\zzz_admin_usernames.sql"
if errorlevel 1 goto :fail

REM --- 5. Start the API (runs in this window; the browser opens when it is ready) ---
set "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:%PGPORT%/casino"
set "WEB_DIR=%~dp0web\dist"

echo [5/5] Starting API on http://localhost:%API_PORT% ...
echo.
echo  Keep this window open while presenting.
echo  Press Ctrl+C (or close the window) to stop.
echo.
start "" /b "%~dp0open_when_ready.bat" %API_PORT%
"%~dp0python\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%

echo.
echo Stopping PostgreSQL...
"%PGBIN%\pg_ctl.exe" -D "%PGDATA%" -m fast stop >nul 2>&1
exit /b 0

:fail
echo.
echo Something went wrong. Check initdb.log, postgres.log and seed.log in this folder.
"%PGBIN%\pg_ctl.exe" -D "%PGDATA%" -m fast stop >nul 2>&1
pause
exit /b 1
