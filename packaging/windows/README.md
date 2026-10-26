# Windows portable bundle

The bundle runs its own PostgreSQL and Python from this folder. It does not install either
application, create a Windows service, or require administrator rights. It works whether or not the
presentation PC already has Python or PostgreSQL installed. The dashboard is available locally and
does not need internet access after the bundle has been built.

## 1. Build the bundle (on your dev machine)

1. Install Node.js/npm on the build PC, then install the web dependencies once:
   ```
   cd web
   npm ci
   cd ..
   ```
   `build_bundle.ps1` runs `npm run build` automatically each time it creates the ZIP. This refreshes
   `web/dist` from the current `web/src` before packaging. Node.js/Vite are needed on the build PC
   only; the portable ZIP serves the compiled frontend and does not run Vite.
2. Install a normal Python 3.12 (only used to download wheels) and the
   [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)
   if this PC does not have it (the script copies its DLLs into the bundle).
3. Save these two files in `packaging/windows/downloads/`:
   - Python **Windows embeddable package (64-bit)**, 3.12.x: <https://www.python.org/downloads/windows/>
   - PostgreSQL **Windows x86-64 binaries (zip)**: <https://www.enterprisedb.com/download-postgresql-binaries>
4. From the repo root:
   ```
   powershell -ExecutionPolicy Bypass -File packaging\windows\build_bundle.ps1
   ```
   Output: `dist\casino-demo.zip`.

If you do not develop on Windows, run the script on a Windows machine or VM (the bundle must be
assembled for Windows x64).

## 2. Presentation checklist

Run it on a clean place, ideally a standard (non-admin) Windows user or a PC without Python/Postgres.

The bundle's `seed\casino_demo.sql` is a PostgreSQL dump containing the schema and fictional demo
records. It is loaded by `start.bat` on the first run; the presentation PC does not need Alembic,
Faker, or NumPy. The startup script checks for free loopback ports and selects a port in the
configured range when the default is occupied. It never connects to or changes a separately
installed PostgreSQL service. Regenerate the dump from the disposable export database as described
in the repository README, then rebuild the bundle.

Seeded demo accounts use the username and password printed by the seed generator. With the default
seed settings, the password is `Demo-Casino-2026!`; for example, `andres.molina` is a seeded
super-admin account. These credentials and all generated records are fictional and for local
presentation use only.

- [ ] Right-click the downloaded zip -> Properties -> **Unblock** (if it came from the internet), then extract.
- [ ] Double-click `start.bat`. If SmartScreen warns: "More info" -> "Run anyway".
- [ ] Note the local URL printed in the console; the port may change if a service already uses the
      default. The browser should open on the Casino Admin sign-in page.
- [ ] Sign in with a seeded administrator username and password.
- [ ] Confirm the Players page loads records, then sign out and sign in again.
- [ ] Check `<printed URL>/api/health` returns `{"status":"ok"}` and
      `<printed URL>/api/db-check` reports the database and seed as loaded.
- [ ] Close the window, run `start.bat` again (the second run must keep the database and allow normal sign-in).
- [ ] Delete the `data\` folder and run again (simulates a first run).
- [ ] Repeat with the network disconnected.
- [ ] Confirm the existing Python/PostgreSQL installations and services remain unchanged.
- [ ] Try it on a real university PC if you can: some block unknown `.exe`/`.bat` (AppLocker).

## 3. If something fails

| Symptom | Likely cause |
|---|---|
| Missing `VCRUNTIME140.dll` / `MSVCP140.dll` (or similar) | Rebuild with the current `build_bundle.ps1`, which copies the VC++ runtime DLLs into `pgsql\bin` and `python\`. Manual fix: copy `vcruntime140*.dll`, `msvcp140*.dll` and `concrt140.dll` from `C:\Windows\System32` of a PC that has the VC++ Redistributable (x64) into `pgsql\bin` |
| `initdb.log` reports a path or permission error | Extract to a folder the current Windows user can write to, such as their profile or Documents |
| Window closes immediately / program does not start | Check the local logs and whether policy/antivirus blocks unknown `.exe`/`.bat` files; ask the institution's IT team |
| No free port found | Close an application using the configured ranges (`55432-55532` for PostgreSQL, `8000-8099` for the API), then retry |

The package is self-contained for offline use; the dashboard uses system fonts and the API and
database runtimes are packaged with the app.

## Current package validation

The current `dist\casino-demo.zip` was built from the production frontend, the portable API
dependencies, PostgreSQL 16.15 binaries, and a reproducible database dump (seed `42`, as-of
`2026-10-23`). The ZIP is about 77 MB.

The extracted bundle was exercised on this Windows machine from a non-elevated session with only
Windows system tools on `PATH`. Other development services were already using ports 8000 and 55432;
the package selected 8001 and 55433 and ran its own embedded Python and PostgreSQL. The first run
loaded 1,200 players and 163,273 bets; health and database checks passed; the seeded super-admin
could sign in through the real browser UI and open Players. A second run preserved the data, and
removing only the test bundle's `data\` directory correctly triggered a clean first-run restore.
The bundled database shut down cleanly after each run.

This verifies the portable runtime and port-collision behavior locally, but is not a substitute for
the final rehearsal in a separate clean VM with the network disconnected. Complete the checklist
above on the presentation VM, as a standard Windows user, before the presentation.
