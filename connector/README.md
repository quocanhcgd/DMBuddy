# Printbuddy Connector prototype

This standalone agent is the first Phase 1 prototype. It enrolls with a
Printbuddy server, stores the returned credential in a local state file, opens
an outbound WSS connection and sends heartbeats. It can perform bounded TCP
discovery on a private LAN when requested by an authorized Printbuddy user;
it does not yet control printers.

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
