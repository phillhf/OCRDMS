# Baut dist\OCRDMS (PyInstaller) und dist\OCRDMS-Setup-<Version>.exe (Inno Setup).
# Die Version kommt ausschließlich aus src\ocrdms\__init__.py.
# Aufruf aus dem Projektordner:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$init = Get-Content "src\ocrdms\__init__.py" -Raw
if ($init -notmatch '__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"') { throw "Version in src\ocrdms\__init__.py nicht gefunden" }
$version = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
$tuple = "($($Matches[1]), $($Matches[2]), $($Matches[3]), 0)"
Write-Host "Baue OCRDMS $version"

# Versionsinfo der EXE aktualisieren
$vi = Get-Content "packaging\version_info.txt" -Raw
$vi = $vi -replace 'filevers=\([^)]*\)', "filevers=$tuple" -replace 'prodvers=\([^)]*\)', "prodvers=$tuple"
$vi = $vi -replace '("(?:File|Product)Version", ")[^"]*(")', "`${1}$version`${2}"
Set-Content "packaging\version_info.txt" $vi -NoNewline -Encoding utf8

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $python -m PyInstaller packaging\ocrdms.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 nicht gefunden (winget install JRSoftware.InnoSetup)" }
& $iscc /Qp "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fehlgeschlagen" }

Write-Host "Fertig: dist\OCRDMS-Setup-$version.exe"
