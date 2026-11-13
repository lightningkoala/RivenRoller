# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
# Creates a private Python environment in this folder (.venv) on first run,
# installs hash-locked dependencies, then starts RivenRoller. Touches nothing
# outside this folder and RivenRoller's own data folder.
param([switch]$Console)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$pythonw = Join-Path $venv 'Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Install 64-bit Python 3.13 or 3.14 from python.org (with the "py" launcher), then run this again.'
    }
    $version = $null
    foreach ($candidate in '3.13', '3.14') {
        # Through cmd so a missing version's error text can't stop this script.
        cmd /c "py -$candidate-64 -c pass >nul 2>&1"
        if ($LASTEXITCODE -eq 0) { $version = $candidate; break }
    }
    if (-not $version) { throw 'Python 3.13 or 3.14 (64-bit) was not found.' }
    Write-Host "Creating RivenRoller's Python environment (Python $version)..."
    & py "-$version-64" -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

$locks = @('requirements.txt', 'roller-requirements.txt') | ForEach-Object {
    (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root $_)).Hash
}
$stamp = Join-Path $venv 'installed-locks.txt'
$wanted = $locks -join ';'
if (-not (Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $wanted) {
    Write-Host 'Installing dependencies (first run or after an update)...'
    & $python -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing the RivenLens engine dependencies failed.' }
    & $python -m pip install --disable-pip-version-check --require-hashes -r (Join-Path $root 'roller-requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing vgamepad or segno failed.' }
    Set-Content -LiteralPath $stamp -Value $wanted
}

$main = Join-Path $root 'roller\main.py'
if ($Console) {
    # Shows errors in this window; use it if RivenRoller doesn't open.
    & $python $main
} else {
    Start-Process -FilePath $pythonw -ArgumentList ('"' + $main + '"') -WorkingDirectory $root
}
