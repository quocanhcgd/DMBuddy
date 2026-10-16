# Printbuddy Connector prototype

This standalone agent is the first Phase 1 prototype. It enrolls with a
Printbuddy server, stores the returned credential in a local state file, opens
an outbound WSS connection and sends heartbeats. It can perform bounded TCP
discovery and provider verification for Bambu MQTT, Moonraker HTTP, and
PrusaLink HTTP when requested by an authorized Printbuddy user; it does not yet
control printers.

Provider verification credentials are used only in memory for the short-lived
authenticated WSS request. They are not written to the Connector state file,
logs, or verification result.

## Run locally

From the repository root, with the backend dependencies installed:

```powershell
$env:PRINTBUDDY_SERVER_URL = "https://printbuddy.example.com"
$env:PRINTBUDDY_ENROLLMENT_CODE = "pc_..."  # only for first run
$env:PRINTBUDDY_CONNECTOR_STATE = "C:\ProgramData\Printbuddy\connector-state.json"
python connector/printbuddy_connector.py
```

The enrollment code is single-use. The credential is written only to the local
state file and is never logged. Delete/revoke the Connector in Printbuddy before
enrolling a replacement agent.

## Run with Docker (Linux)

The standalone compose file uses host networking so the Connector can reach
printers on the host's private LAN interfaces. It does not publish an inbound
port; the long-lived connection is outbound WSS to Printbuddy.

From the repository root:

```bash
export PRINTBUDDY_SERVER_URL="https://printbuddy.example.com"
export PRINTBUDDY_ENROLLMENT_CODE="pc_..."  # first run only
docker compose -f connector/docker-compose.yml up -d --build
docker compose -f connector/docker-compose.yml logs -f printbuddy-connector
```

The enrollment code is consumed once. After enrollment, remove it from the
shell environment and compose override. The credential remains in the named
`printbuddy_connector_state` volume, owned by a non-root container user.

## Windows and Docker Desktop

Docker Desktop does not provide Linux host networking with the same semantics.
Use the native Windows scripts in `connector/windows` on the Windows host:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\connector\windows\install-connector-task.ps1 `
  -ServerUrl "https://printbuddy.example.com"
```

The installer installs Python dependencies, performs one enrollment in a
short-lived process, then registers the Connector to start at the current
user's logon. It prompts for the one-time enrollment code instead of placing
it in the PowerShell command line. The state file is stored under the current user's
`%LOCALAPPDATA%\Printbuddy\Connector`; the enrollment code is not written into
the scheduled task.
Remove it from your shell after installation. To remove the task:

```powershell
.\connector\windows\uninstall-connector-task.ps1
```

### Windows executable

To create a self-contained Windows executable, run this from the repository
root on a Windows machine with Python installed:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\connector\windows\build-exe.ps1
```

The output is `connector\windows\dist\PrintbuddyConnector.exe`. Install it
with the same one-time enrollment flow:

```powershell
.\connector\windows\install-connector-task.ps1 `
  -ServerUrl "https://printbuddy.example.com" `
  -ExecutablePath ".\connector\windows\dist\PrintbuddyConnector.exe"
```

The executable reads `PRINTBUDDY_SERVER_URL`,
`PRINTBUDDY_CONNECTOR_STATE`, and the one-time enrollment code from its
process environment. The enrollment code is never put in the scheduled task
arguments or written to disk. One-file PyInstaller startup can be slower and
some antivirus products may inspect or quarantine unsigned builds; publish a
signed release executable for production use. Python mode remains available
by omitting `-ExecutablePath`.

Docker Desktop does not provide Linux host networking with the same semantics.
If Docker Desktop is used instead, remove `network_mode: host` and define a
reachable bridge network. Verify from inside the container that each private
printer IP and provider port is reachable before using discovery.

## Operating rules

- Allow outbound TCP 443 (or the configured HTTPS/WSS endpoint) from the
  Connector host to Printbuddy.
- Do not expose or port-forward the Connector container.
- Keep the state file/volume private; it contains the long-lived Connector
  credential.
- Revoke the Connector in Printbuddy before deleting or copying its state.
- The current prototype supports discovery, provider verification and status
  reachability only; it does not yet transfer files or control printers.
