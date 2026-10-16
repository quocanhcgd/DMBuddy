# Printbuddy Codebase Index

## Top-level map

| Path | Role |
|---|---|
| `backend/` | FastAPI app, SQLAlchemy models/schemas/services, pytest |
| `frontend/` | React 19 + Vite + TypeScript SPA, Vitest |
| `gcode_viewer/` | PrettyGCode/Three.js static viewer and adapter |
| `slicer-api/` | Optional OrcaSlicer/BambuStudio sidecar compose context |
| `updater/` | Optional Docker self-update sidecar |
| `deploy/` | Entrypoint and systemd deployment files |
| `install/` | Native/Docker installation and update scripts |
| `static/` | Built frontend and runtime images/icons/fonts |
| `docs/` | Deployment/integration/design documentation and this memory |
| `tests/` | E2E tests outside backend/frontend test trees |
| `scripts/` | Maintenance/import/debug/backfill utilities |
| `.github/` | CI, issue templates and release automation |

## Backend map

```text
backend/app/main.py                 FastAPI app, lifespan, callbacks, mounts
backend/app/cli.py                  Minimal CLI entrypoint
backend/app/core/config.py          Settings, paths, version, env
backend/app/core/database.py        Async engine/session, schema/migrations/seeds
backend/app/core/auth.py            JWT/auth dependencies
backend/app/core/permissions.py     Permission helpers
backend/app/core/websocket.py       Broadcast connection manager
backend/app/api/routes/             HTTP/WebSocket API surface
backend/app/models/                 SQLAlchemy persistence models
backend/app/schemas/                Pydantic request/response contracts
backend/app/services/               Domain/integration/background logic
backend/app/services/printer_providers/
                                    Provider factory and printer clients
backend/app/services/virtual_printer/
                                    FTP/MQTT/SSDP/TCP emulation
backend/app/utils/                  Pure helpers and 3MF/color/path utilities
backend/app/data/                   Slicer field metadata JSON
```

## Frontend map

```text
frontend/src/main.tsx               React bootstrap
frontend/src/App.tsx                Providers, guards, router and page map
frontend/src/api/client.ts          HTTP API client and typed calls
frontend/src/pages/                 Route-level screens
frontend/src/components/            Reusable UI and domain components
frontend/src/components/PrintModal/ Print/plate/printer/filament flow
frontend/src/contexts/              Auth/theme/toast/color/slice state
frontend/src/hooks/                 WebSocket/camera/query interaction hooks
frontend/src/utils/                 Formatting, printer, slicer, file helpers
frontend/src/i18n/                  i18next setup and locale dictionaries
frontend/src/__tests__/             Vitest + Testing Library tests
frontend/vite.config.ts             Dev proxy, build output, gcode viewer middleware
```

## High-value files by task

| Task | Start here | Then inspect |
|---|---|---|
| Add printer/provider | `api/routes/printers.py`, `services/printer_manager.py` | `services/printer_providers/*`, `models/printer.py`, printer tests, `PrintersPage.tsx` |
| Print start/complete | `main.py` callbacks | `print_scheduler.py`, `background_dispatch.py`, archive/notification/Spoolman services |
| Queue/scheduling | `api/routes/print_queue.py` | `models/print_queue.py`, `print_scheduler.py`, Queue page/tests |
| Archive/library | `api/routes/archives.py`, `api/routes/library.py` | `services/archive.py`, `models/archive.py`, path/3MF tests |
| Filament/AMS/Spoolman | inventory/spoolman routes | spool models/services, `FilamentMapping`, inventory tests |
| Camera/timelapse | `api/routes/camera.py` | camera services, `CameraPage`, camera/timelapse tests |
| Auth/permissions | `api/routes/auth.py`, `core/auth.py` | `User`/`Group`, `PermissionRoute`, auth/MFA tests |
| Settings/integrations | `api/routes/settings.py` | `core/config.py`, integration services, `SettingsPage` |
| Realtime UI | `core/websocket.py`, route `websocket.py` | `useWebSocket.ts`, query keys and event tests |
| Slicing | `api/routes/slice_jobs.py`, `services/slicer_api.py` | `slice_dispatch.py`, 3MF conversion, `SliceModal` |
| Deploy/update | `docker-compose.yml`, `Dockerfile` | `deploy/docker-entrypoint.sh`, updater, deployment docs |

## Provider files

- `backend/app/services/printer_providers/base.py`: common protocol only.
- `bambu.py`: factory wrapper around legacy Bambu MQTT client.
- `moonraker.py`: Klipper/Mainsail/Fluidd.
- `prusalink.py`: local PrusaLink.
- `prusaconnect.py`: Prusa Connect.
- `elegoo_sdcp.py`: Elegoo SDCP.
- `factory.py`: supported values, aliases and client selection.

## Test index

- Backend unit/service tests: `backend/tests/unit/` and `backend/tests/unit/services/`.
- Backend API fixtures/config: `backend/tests/conftest.py`, `backend/tests/pytest.ini`.
- Frontend tests: `frontend/src/__tests__/` grouped by api/components/utils/pages.
- E2E: `tests/e2e_comprehensive_test.py`, `tests/e2e_toggle_persistence_test.py`.
- Security/static checks: `test_security.sh`, `.github/workflows/ci.yml`, `.codeql/`.

## Generated inventory command

```powershell
$files = rg --files -g '!node_modules' -g '!vendor' -g '!dist' -g '!build' -g '!coverage'
"ALL=$($files.Count)"
"PY=$((@($files | Where-Object {$_ -match '\.py$'})).Count)"
"TS=$((@($files | Where-Object {$_ -match '\.(ts|tsx)$'})).Count)"
"JS=$((@($files | Where-Object {$_ -match '\.(js|jsx|mjs)$'})).Count)"
```

