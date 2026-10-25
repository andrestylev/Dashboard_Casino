# Windows portable bundle (Phase 0 spike)

Goal: prove, **before building the dashboard**, that API + PostgreSQL + frontend run on a Windows
PC with **no admin rights, no installs and no internet**.

## 1. Build the bundle (on your dev machine)

1. Install a normal Python 3.12 (only used to download wheels) and the
   [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)
   if this PC does not have it (the script copies its DLLs into the bundle).
2. Save these two files in `packaging/windows/downloads/`:
   - Python **Windows embeddable package (64-bit)**, 3.12.x: <https://www.python.org/downloads/windows/>
   - PostgreSQL **Windows x86-64 binaries (zip)**: <https://www.enterprisedb.com/download-postgresql-binaries>
3. From the repo root:
   ```
   powershell -ExecutionPolicy Bypass -File packaging\windows\build_bundle.ps1
   ```
   Output: `dist\casino-demo.zip`.

If you do not develop on Windows, run the script on a Windows machine or VM (the bundle must be
assembled for Windows x64).

## 2. Spike checklist (the part that really matters)

Run it on a clean place, ideally a standard (non-admin) Windows user or a PC without Python/Postgres.

The bundle's `seed\casino_demo.sql` is a plain PostgreSQL dump containing both the schema and the
fictional demo records. It is loaded by `start.bat` on the first run; the presentation PC does not
need Alembic, Faker, or NumPy. Regenerate the dump from the development stack as described in the
repository README, then rebuild the bundle. Demo administrator credentials are not production
credentials.

- [ ] Right-click the downloaded zip -> Properties -> **Unblock** (if it came from the internet), then extract
      to a path **without spaces or accents** (e.g. `C:\Users\<user>\casino-demo`).
- [ ] Double-click `start.bat`. If SmartScreen warns: "More info" -> "Run anyway".
- [ ] The browser opens on the Casino Admin sign-in page.
- [ ] Sign in with a seeded administrator username and password.
- [ ] Confirm the Players page loads records, then sign out and sign in again.
- [ ] Check `http://localhost:8000/api/health` returns `{"status":"ok"}` and
      `http://localhost:8000/api/db-check` reports the database and seed as loaded.
- [ ] Close the window, run `start.bat` again (the second run must keep the database and allow normal sign-in).
- [ ] Delete the `data\` folder and run again (simulates a first run).
- [ ] Repeat with the network disconnected.
- [ ] Try it on a real university PC if you can: some block unknown `.exe`/`.bat` (AppLocker).

## 3. If something fails

| Symptom | Likely cause |
|---|---|
| Missing `VCRUNTIME140.dll` / `MSVCP140.dll` (or similar) | Rebuild with the current `build_bundle.ps1`, which copies the VC++ runtime DLLs into `pgsql\bin` and `python\`. Manual fix: copy `vcruntime140*.dll`, `msvcp140*.dll` and `concrt140.dll` from `C:\Windows\System32` of a PC that has the VC++ Redistributable (x64) into `pgsql\bin` |
| `initdb.log` complains about the path | Move the folder to a path without spaces/accents |
| Window closes immediately / program does not start | Blocked by policy (AppLocker, antivirus): use the video backup |
| Port already in use | Change `PGPORT` / `API_PORT` at the top of `start.bat` |

The bundle is intended to run locally without internet access; the dashboard uses system fonts and
the API and database are packaged with the app.
