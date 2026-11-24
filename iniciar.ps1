$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path '.venv\Scripts\python.exe') {
    $stationPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
} elseif ($pythonCommand) {
    $stationPython = $pythonCommand.Source
} elseif (Test-Path -LiteralPath $runtimePython) {
    $stationPython = $runtimePython
} else {
    throw 'Instala Python 3.10 o superior y sigue README.md.'
}
if (Test-Path '.deps') { $env:PYTHONPATH = Join-Path $PSScriptRoot '.deps' }
& $stationPython app.py
