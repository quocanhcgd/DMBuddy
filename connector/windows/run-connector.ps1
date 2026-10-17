[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ServerUrl,

    [string] $EnrollmentCode = '',

    [string] $StatePath = "$env:LOCALAPPDATA\Printbuddy\Connector\connector-state.json",

    [string] $PythonPath = 'python',

    [string] $ExecutablePath = '',

    [switch] $AgentMode
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $scriptRoot
$stateDirectory = Split-Path -Parent $StatePath
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

$env:PRINTBUDDY_SERVER_URL = $ServerUrl.TrimEnd('/')
$env:PRINTBUDDY_CONNECTOR_STATE = $StatePath
$env:PRINTBUDDY_CONNECTOR_VERSION = if ($env:PRINTBUDDY_CONNECTOR_VERSION) { $env:PRINTBUDDY_CONNECTOR_VERSION } else { '0.1.0' }
if ($EnrollmentCode) {
    $env:PRINTBUDDY_ENROLLMENT_CODE = $EnrollmentCode
} else {
    Remove-Item Env:PRINTBUDDY_ENROLLMENT_CODE -ErrorAction SilentlyContinue
}

Push-Location $repositoryRoot
try {
    if ($ExecutablePath) {
        $resolvedExecutable = (Resolve-Path -LiteralPath $ExecutablePath -ErrorAction Stop).Path
        if ($AgentMode) {
            & $resolvedExecutable '--agent'
        } else {
            & $resolvedExecutable
        }
    } else {
        $python = (Get-Command $PythonPath -ErrorAction Stop).Source
        & $python -m connector.printbuddy_connector
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
