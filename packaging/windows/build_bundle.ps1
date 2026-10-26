<#
Builds dist\casino-demo.zip, the portable Windows bundle (no installation, no admin needed to run it).

Build-machine prerequisites:
  - Node.js/npm and the web dependencies installed once with `cd web; npm ci`.
  - A normal Python 3.12, used only to download Windows wheels.
  - Python and PostgreSQL portable archives saved in packaging\windows\downloads\:
  1) Python "Windows embeddable package (64-bit)" for the SAME minor version as the
     Python used here (e.g. python-3.12.x-embed-amd64.zip)  -> https://www.python.org/downloads/windows/
  2) PostgreSQL "Windows x86-64 binaries (zip)" from EnterpriseDB
     (e.g. postgresql-16.x-x-windows-x64-binaries.zip)       -> https://www.enterprisedb.com/download-postgresql-binaries

This machine also needs the 'Microsoft Visual C++ Redistributable (x64)' installed. The script copies
its runtime DLLs into the bundle, so the presentation PC does not need to install anything:
  https://aka.ms/vs/17/release/vc_redist.x64.exe

Run (no admin needed):
  powershell -ExecutionPolicy Bypass -File packaging\windows\build_bundle.ps1
#>
param(
  [string]$PythonZip,
  [string]$PostgresZip,
  [string]$HostPython = "python",  # a normal Python on this machine, used only to download wheels
  [string]$RuntimeDir              # where the VC++ runtime DLLs live (default: 64-bit System32)
)
$ErrorActionPreference = "Stop"

if (-not $RuntimeDir) {
  # A 32-bit PowerShell would be redirected to the 32-bit DLLs; Sysnative reaches the 64-bit ones.
  if ([Environment]::Is64BitProcess) { $RuntimeDir = Join-Path $env:SystemRoot "System32" }
  else { $RuntimeDir = Join-Path $env:SystemRoot "Sysnative" }
}

$root      = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$downloads = Join-Path $PSScriptRoot "downloads"

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
  throw "Node.js and npm are required to build the latest frontend. Install Node.js on the build machine and retry."
}

Write-Host "[1/7] Building the latest frontend with Vite ..."
Push-Location (Join-Path $root "web")
try {
  & $npm.Source run build
  if ($LASTEXITCODE -ne 0) {
    throw "Frontend build failed (exit code $LASTEXITCODE). If dependencies are missing, run 'npm ci' in the web folder, then retry."
  }
} finally {
  Pop-Location
}

foreach ($required in @(
  (Join-Path $root "web\dist\index.html"),
  (Join-Path $root "seed\casino_demo.sql"),
  (Join-Path $PSScriptRoot "find_free_port.ps1")
)) {
  if (-not (Test-Path $required -PathType Leaf)) {
    throw "Required bundle input not found: $required. Prepare the demo SQL dump and confirm the frontend build succeeded."
  }
}

function Find-Zip($explicit, $pattern, $label) {
  if ($explicit) { return (Resolve-Path $explicit).Path }
  $f = Get-ChildItem $downloads -Filter $pattern -ErrorAction SilentlyContinue |
       Sort-Object Name | Select-Object -Last 1
  if (-not $f) { throw "Missing $label zip. Save it in $downloads (see the header of this script)." }
  return $f.FullName
}
$PythonZip   = Find-Zip $PythonZip   "python-*-embed-amd64.zip"                "Python embeddable"
$PostgresZip = Find-Zip $PostgresZip "postgresql-*-windows-x64-binaries.zip"   "PostgreSQL binaries"

$zipName = Split-Path $PythonZip -Leaf
if ($zipName -match 'python-(\d+)\.(\d+)\.\d+-embed') {
  $pyDot = "$($Matches[1]).$($Matches[2])"
  $pyTag = "$($Matches[1])$($Matches[2])"
} else {
  throw "Cannot read the Python version from '$zipName'."
}

$dist   = Join-Path $root "dist"
$bundle = Join-Path $dist "casino-demo"
if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force }
New-Item -ItemType Directory -Path $bundle | Out-Null

Write-Host "[2/7] Extracting embeddable Python $pyDot ..."
Expand-Archive -Path $PythonZip -DestinationPath (Join-Path $bundle "python")

Write-Host "[3/7] Downloading dependencies for Windows x64 / Python $pyDot ..."
$site = Join-Path $bundle "python\Lib\site-packages"
New-Item -ItemType Directory -Path $site -Force | Out-Null
& $HostPython -m pip install -r (Join-Path $root "api\requirements.txt") `
    --target $site --only-binary=:all: --platform win_amd64 `
    --python-version $pyDot --implementation cp --abi "cp$pyTag" --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

Write-Host "[4/7] Configuring the embeddable Python search paths ..."
$pth = Get-ChildItem (Join-Path $bundle "python") -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "python*._pth not found: is this really the embeddable package?" }
@("python$pyTag.zip", ".", "Lib\site-packages", "..\api", "import site") |
    Set-Content -Path $pth.FullName -Encoding ASCII

Write-Host "[5/7] Extracting PostgreSQL binaries ..."
Expand-Archive -Path $PostgresZip -DestinationPath $bundle
if (-not (Test-Path (Join-Path $bundle "pgsql\bin\pg_ctl.exe"))) {
  throw "pgsql\bin\pg_ctl.exe not found after extraction (unexpected zip layout)."
}
# Trim what the demo never uses (keeps the bundle much smaller).
foreach ($name in @("pgAdmin 4", "StackBuilder", "doc", "symbols")) {
  Remove-Item (Join-Path $bundle "pgsql\$name") -Recurse -Force -ErrorAction SilentlyContinue
}

# VC++ runtime DLLs, deployed app-local so the presentation PC needs no installer and no admin rights.
$runtimeDlls = @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
                 "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll")
$copied = @()
foreach ($dll in $runtimeDlls) {
  $src = Join-Path $RuntimeDir $dll
  if (-not (Test-Path $src)) { continue }
  Copy-Item $src (Join-Path $bundle "pgsql\bin") -Force
  $pyDest = Join-Path $bundle "python\$dll"
  if (-not (Test-Path $pyDest)) { Copy-Item $src $pyDest }   # keep the newer copy Python ships with
  $copied += $dll
}
if (($copied -notcontains "vcruntime140.dll") -or ($copied -notcontains "msvcp140.dll")) {
  throw "VC++ runtime DLLs not found in $RuntimeDir. Install the 'Microsoft Visual C++ Redistributable (x64)' on this machine (https://aka.ms/vs/17/release/vc_redist.x64.exe) and run again."
}
Write-Host "      runtime DLLs bundled: $($copied -join ', ')"

Write-Host "[6/7] Copying the application ..."
New-Item -ItemType Directory -Path (Join-Path $bundle "api") | Out-Null
Copy-Item (Join-Path $root "api\app") (Join-Path $bundle "api\app") -Recurse
Get-ChildItem (Join-Path $bundle "api") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $bundle "web") | Out-Null
Copy-Item (Join-Path $root "web\dist") (Join-Path $bundle "web\dist") -Recurse
Copy-Item (Join-Path $root "seed") (Join-Path $bundle "seed") -Recurse
foreach ($f in @("start.bat", "stop.bat", "open_when_ready.bat", "find_free_port.ps1")) {
  Copy-Item (Join-Path $PSScriptRoot $f) $bundle
}
@(
  "Casino Admin - local demo",
  "",
  "1. Double-click start.bat (first run takes a few seconds).",
  "2. The browser opens at the local URL printed by start.bat.",
  "   A free local port is selected automatically.",
  "3. To quit: close the black window, or run stop.bat.",
  "",
  "Demo super-admin username: andres.molina",
  "Demo password: Demo-Casino-2026!",
  "These credentials and data are fictional; local demo use only."
) | Set-Content -Path (Join-Path $bundle "README.txt") -Encoding ASCII

Write-Host "[7/7] Creating the zip ..."
$zip = Join-Path $dist "casino-demo.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $bundle -DestinationPath $zip

$mb = [math]::Round((Get-Item $zip).Length / 1MB)
Write-Host "Done: $zip ($mb MB)"
