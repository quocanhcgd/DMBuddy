[CmdletBinding()]
param(
    [string] $PythonPath = 'python',

    [string] $OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
$windowsRoot = $PSScriptRoot
$connectorRoot = Split-Path -Parent $windowsRoot
$repositoryRoot = Split-Path -Parent $connectorRoot
$python = (Get-Command $PythonPath -ErrorAction Stop).Source

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $windowsRoot 'dist'
}
$buildDirectory = Join-Path $windowsRoot 'build'
$specDirectory = Join-Path $windowsRoot 'spec'
New-Item -ItemType Directory -Force -Path $OutputDirectory, $buildDirectory, $specDirectory | Out-Null

Push-Location $repositoryRoot
try {
    & $python -c 'import httpx, pydantic, websockets, paho.mqtt.client' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Connector runtime dependencies are missing. Installing them...'
        & $python -m pip install -r (Join-Path $connectorRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Could not install Connector Python dependencies.' }
    }
}
finally {
    Pop-Location
}

& $python -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'PyInstaller is not installed. Installing it for the current Python environment...'
    & $python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'Could not install PyInstaller.' }
}

$entryPoint = Join-Path $connectorRoot 'printbuddy_connector.py'
$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onefile',
    '--name', 'PrintbuddyConnector',
    '--paths', $repositoryRoot,
    '--hidden-import', 'paho.mqtt.client',
    '--distpath', $OutputDirectory,
    '--workpath', $buildDirectory,
    '--specpath', $specDirectory,
    $entryPoint
)

Push-Location $repositoryRoot
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to build PrintbuddyConnector.exe.' }
}
finally {
    Pop-Location
}

$executable = Join-Path $OutputDirectory 'PrintbuddyConnector.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Expected executable was not created: $executable"
}
Write-Host "Built: $executable"
