[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ServerUrl,

    [string] $EnrollmentCode = '',

    [string] $TaskName = 'Printbuddy Connector',

    [string] $PythonPath = 'python',

    [string] $ExecutablePath = ''
)

$ErrorActionPreference = 'Stop'
$windowsRoot = $PSScriptRoot
$connectorRoot = Split-Path -Parent $windowsRoot
$repositoryRoot = Split-Path -Parent $connectorRoot
$runScript = Join-Path $PSScriptRoot 'run-connector.ps1'
$statePath = Join-Path $env:LOCALAPPDATA 'Printbuddy\Connector\connector-state.json'
$stateDirectory = Split-Path -Parent $statePath
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

$python = $null
if ($ExecutablePath) {
    $ExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath -ErrorAction Stop).Path
} else {
    $python = (Get-Command $PythonPath -ErrorAction Stop).Source
    Push-Location $repositoryRoot
    try {
        & $python -c 'import httpx, pydantic, websockets, paho.mqtt.client' 2>$null
        if ($LASTEXITCODE -ne 0) {
            & $python -m pip install -r (Join-Path $connectorRoot 'requirements.txt')
            if ($LASTEXITCODE -ne 0) { throw 'Could not install Connector Python dependencies.' }
        }
    }
    finally {
        Pop-Location
    }
}

# Enrollment is performed once in a short-lived child process. The code is
# passed through the current process environment and never stored in the task.
if (-not (Test-Path $statePath)) {
    if (-not $EnrollmentCode) {
        $EnrollmentCode = Read-Host 'Enter the one-time Printbuddy enrollment code'
    }
    if (-not $EnrollmentCode) {
        throw 'EnrollmentCode is required for the first installation.'
    }
    $env:PRINTBUDDY_SERVER_URL = $ServerUrl.TrimEnd('/')
    $env:PRINTBUDDY_ENROLLMENT_CODE = $EnrollmentCode
    $env:PRINTBUDDY_CONNECTOR_STATE = $statePath
    if ($ExecutablePath) {
        $bootstrap = Start-Process -FilePath $ExecutablePath -WorkingDirectory (Split-Path -Parent $ExecutablePath) -WindowStyle Hidden -PassThru
    } else {
        $bootstrap = Start-Process -FilePath $python -ArgumentList '-m', 'connector.printbuddy_connector' -WorkingDirectory $repositoryRoot -WindowStyle Hidden -PassThru
    }
    try {
        $deadline = (Get-Date).AddSeconds(60)
        while (-not (Test-Path $statePath) -and (Get-Date) -lt $deadline) {
            if ($bootstrap.HasExited) { break }
            Start-Sleep -Seconds 1
        }
        if (-not (Test-Path $statePath)) {
            throw 'Connector enrollment did not create the state file within 60 seconds.'
        }
    }
    finally {
        if (-not $bootstrap.HasExited) { Stop-Process -Id $bootstrap.Id -Force }
        Remove-Item Env:PRINTBUDDY_ENROLLMENT_CODE -ErrorAction SilentlyContinue
        $EnrollmentCode = $null
    }
}

$escapedRunScript = $runScript.Replace('"', '\"')
$escapedServerUrl = $ServerUrl.Replace('"', '\"')
$escapedStatePath = $statePath.Replace('"', '\"')
$escapedExecutablePath = if ($ExecutablePath) { $ExecutablePath.Replace('"', '\"') } else { '' }
$runtimeArgument = if ($ExecutablePath) {
    "-ExecutablePath `"$escapedExecutablePath`""
} else {
    "-PythonPath `"$python`""
}
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$escapedRunScript`" -ServerUrl `"$escapedServerUrl`" -StatePath `"$escapedStatePath`" $runtimeArgument"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repositoryRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType InteractiveToken -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Description 'Printbuddy outbound Connector' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started scheduled task: $TaskName"
Write-Host "State file: $statePath"
