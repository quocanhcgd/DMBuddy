# Printbuddy System Memory

> Tài liệu này là bản ghi nhớ kiến trúc phục vụ các lần điều chỉnh tiếp theo. Nó được lập từ toàn bộ cây file trong workspace và kiểm tra chi tiết các entrypoint, cấu hình, lớp core, route registry, model, provider, service nền, frontend routing, realtime protocol, deployment và test harness.

## 1. Phạm vi và quy mô

Snapshot lập ngày 2026-10-14 trong workspace `F:\Printbuddy`.

- 1.297 file được lập chỉ mục, không tính các thư mục build/vendor bị loại khỏi inventory.
- Backend Python: khoảng 105k dòng trong `backend/app`.
- Frontend TypeScript/TSX: khoảng 190k dòng trong `frontend/src`.
- Backend có 55 route module, 50 model module, 35 schema module và khoảng 104 service module.
- Frontend có 31 page chính, hơn 100 component/hook/context/utility và test Vitest/Testing Library.
- `gcode_viewer/` là viewer PrettyGCode vendored, được phục vụ trực tiếp; không phải một bundle React.
- `slicer-api/` là context Docker cho sidecar slicer, không phải service Python nằm trong app backend.

Số dòng là số đo định hướng, không phải API contract. Khi code thay đổi, kiểm tra lại bằng các lệnh trong phần 13.

## 2. Sản phẩm và boundary runtime

### 2.1 Runtime chính

```text
Browser
  ├─ React/Vite SPA (frontend/src)
  ├─ /api/v1 HTTP -> FastAPI (backend/app/main.py)
  ├─ /api/v1/ws WebSocket -> ConnectionManager + PrinterManager events
  └─ /gcode-viewer/* -> static PrettyGCode viewer

FastAPI
  ├─ API routes -> schemas -> services -> SQLAlchemy models/database
  ├─ PrinterManager -> provider clients -> printer LAN/cloud protocols
  ├─ background schedulers/workers -> queue, notifications, backups, purge...
  └─ static files -> static/ (frontend build) + gcode_viewer/
```

### 2.2 Entrypoints

- Production container: `uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- Backend application object: `backend/app/main.py` (`app = FastAPI(...)`).
- Frontend development: `cd frontend && npm run dev`; Vite proxy `/api` và `/api/v1/ws` về backend port 8000 mặc định.
- Frontend production build: Vite output vào `static/`; FastAPI phục vụ SPA/assets.
- Docker entrypoint: `deploy/docker-entrypoint.sh` chuẩn hóa owner theo `PUID/PGID`, sau đó hạ quyền bằng `gosu`.
- Optional updater: `updater/app/main.py`, gọi Docker socket qua sidecar với bearer token.
- Optional slicers: `slicer-api/` (OrcaSlicer mặc định port 3003, Bambu Studio port 3001).

## 3. Backend architecture

### 3.1 Core/configuration

- `backend/app/core/config.py`: `Settings`, version `APP_VERSION`, path resolution, env loading và tạo directory.
- Mặc định `api_prefix=/api/v1`, `DATA_DIR` là root dữ liệu; nếu không có `DATA_DIR`, app dùng project root cho local dev.
- Database mặc định `sqlite+aiosqlite:///.../printbuddy.db`; database cũ `bambutrack.db` được migrate tên một lần.
- `DATABASE_URL` chuyển sang PostgreSQL (thường `postgresql+asyncpg://...`).
- `MFA_ENCRYPTION_KEY` được đọc bởi encryption module; nếu bỏ trống, key được tạo/lưu trong data volume.
- `PRINTBUDDY_EXTERNAL_ROOTS` là allowlist colon-separated cho external library roots; rỗng nghĩa là tắt.
- Các env quan trọng khác: `DEBUG`, `LOG_LEVEL`, `LOG_TO_FILE`, `PORT`, `SLICER_API_URL`, `BAMBU_STUDIO_API_URL`, `TRUSTED_FRAME_ORIGINS`, `SELF_UPDATE_ENABLED`, `UPDATER_URL`, `UPDATER_TOKEN`, `DISCOVERY_EXTRA_SUBNETS`, `DISCOVERY_MOONRAKER_PORTS`.

### 3.2 Database và migration

- `backend/app/core/database.py` tạo `AsyncEngine`, `AsyncSession`, declarative `Base`, dialect helper và migration runner.
- `init_db()` import toàn bộ model để đăng ký metadata, `create_all`, chạy migration, re-encrypt secret legacy và seed notification templates, groups, spool/color catalogs.
- SQLite dùng WAL/foreign keys và có các guard chống lock/cancel; PostgreSQL có pool tuning từ settings.
- Migration hiện nằm trong code backend thay vì Alembic. Khi thêm field: cập nhật model, migration idempotent cho SQLite/Postgres, schema nếu public, route/service và test migration.
- Secret nhạy cảm: OIDC client secret và TOTP secret có đường đi re-encrypt theo prefix `fernet:`; lỗi từng row được đếm và public qua encryption status.

### 3.3 API routes

Tất cả router được include tại cuối `backend/app/main.py` với `app_settings.api_prefix`. Các miền chính:

| Prefix | Trách nhiệm |
|---|---|
| `/auth`, `/users`, `/groups` | setup/login/logout, JWT/session, MFA/OIDC/LDAP, users và permissions |
| `/printers` | CRUD, control, status, camera, maintenance/k-profiles liên quan |
| `/archives`, `/library`, `/projects` | archive print, file library/trash, project/3MF/source |
| `/queue`, `/print-log`, `/background-dispatch` | scheduling, print history, upload/start worker |
| `/inventory`, `/filament-catalog`, `/spoolman` | spool, filament catalog, slot mapping, Spoolman sync |
| `/cloud`, `/orca-cloud`, `/slicer` | cloud auth/presets/fields và slicer preset operations |
| `/camera`, `/notifications`, `/notification-templates` | camera proxy/diagnostics, notification providers/digest |
| `/smart-plugs`, `/discovery`, `/virtual-printers` | power control, discovery, Bambu virtual printer |
| `/settings`, `/system`, `/metrics`, `/support`, `/updates` | vận hành, health/metrics, diagnostics, update |
| `/webhook`, `/makerworld`, `/open-filament-database`, `/obico` | external integrations |

Route thường chịu trách nhiệm auth/permission, input schema và orchestration; logic network/file/long-running nên ở service. Một số route lớn (`archives.py`, `printers.py`, `library.py`, `inventory.py`, `auth.py`) là hotspot cần đọc cả test trước khi sửa.

### 3.4 Service domains

- Printer communication: `bambu_mqtt.py`, `bambu_ftp.py`, `bambu_cloud.py`, `printer_manager.py`, `printer_reconnect.py`, `printer_diagnostic.py`.
- Provider implementations: `services/printer_providers/`.
- Print lifecycle: `print_scheduler.py`, `background_dispatch.py`, `slice_dispatch.py`, `print_progress.py`, `print_log.py`, `direct_print_tracking.py`.
- Archive/library: `archive.py`, `archive_comparison.py`, `archive_purge.py`, `library_trash.py`, `slicer_3mf_convert.py`, `stl_thumbnail.py`, `timelapse_processor.py`.
- Filament/Spoolman: `spoolman.py`, `spoolman_tracking.py`, `spool_tag_matcher.py`, `filament_requirements.py`, `pending_slot_assignment.py`.
- Camera/vision: `camera.py`, `external_camera.py`, `camera_fanout.py`, `camera_diagnose.py`, `plate_detection.py`, `layer_timelapse.py`.
- Notification/integration: `notification_service.py`, email, web push/live activity, Home Assistant, MQTT relay, Obico, Git providers, backups.
- Virtual printer: `services/virtual_printer/` gồm FTP, MQTT bridge/server, SSDP, TCP proxy, certificate/Tailscale và manager.

## 4. Printer provider boundary

`services/printer_providers/factory.py` là source of truth cho provider normalization và client creation.

| Provider value | Implementation | Protocol/notes |
|---|---|---|
| `bambu` | `bambu.py` -> legacy `BambuMQTTClient` | MQTT status/control, FTP files; AMS/cloud features nhiều nơi vẫn Bambu-specific |
| `klipper`, `mainsail`, `fluidd` | `moonraker.py` | Moonraker HTTP/WebSocket; UI name không đổi protocol |
| `prusalink` | `prusalink.py` | local PrusaLink HTTP |
| `prusaconnect` | `prusaconnect.py` | Prusa Connect Mobile/cloud |
| `elegoo_sdcp` | `elegoo_sdcp.py` | Elegoo Centauri Carbon SDCP WebSocket |

`PrinterClientProtocol` hiện chỉ là subset dùng bởi `PrinterManager`: connect/disconnect, status staleness, start/list/upload/download/delete/stop/request update. AMS, FTP storage, calibration và capability-specific behavior không được giả định trong protocol chung; route phải kiểm tra provider/capability.

## 5. Application lifespan và background work

`backend/app/main.py::lifespan` là startup/shutdown coordinator. Startup theo thứ tự khái quát:

1. cài asyncio/Windows handler, `init_db`, shared httpx clients;
2. sửa dữ liệu legacy/stuck queue, khôi phục debug logging;
3. gắn callbacks cho `PrinterManager` (status, print start/complete, running observed, AMS, layer, bed cooldown, drying);
4. cấu hình MQTT relay/Panda Breath và restore MQTT smart plugs;
5. connect printers, auto-connect Spoolman và ensure extra fields;
6. start print scheduler, background dispatch, smart-plug scheduler, notification digest/live activity, GitHub/local backup, Obico, library trash/archive purge, AMS history;
7. mount/serve static và xử lý startup state.

Shutdown dừng scheduler/workers, disconnect printers, close clients và dọn camera fan-out. Không tạo task background mới trong route nếu service lifecycle đã có manager tương ứng; phải xử lý cancellation/restart recovery.

## 6. Realtime contract

Backend endpoint: `/api/v1/ws` (`backend/app/api/routes/websocket.py`). Client gửi `ping` mỗi 30 giây và có thể gửi `get_status`. Server gửi initial status rồi broadcast các event chính:

- `printer_status` với `printer_id`, `data`;
- `print_start`, `print_complete`;
- `archive_created`, `archive_updated`;
- `missing_spool_assignment`;
- `background_dispatch` và các event được service broadcast trực tiếp.

`backend/app/core/websocket.py` giữ list connection, serialize JSON và loại connection lỗi. `frontend/src/hooks/useWebSocket.ts` reconnect 3 giây, throttle status khoảng 100ms, debounce query invalidation khoảng 3 giây và dispatch custom browser events. Khi thêm event phải cập nhật cả producer, type/handler frontend, invalidation strategy và test.

## 7. Data model map

- Identity: `User`, `Group`, API keys/tokens, OIDC, OTP/TOTP, ephemeral auth.
- Fleet: `Printer`, fleet groups, maintenance, AMS history/labels, virtual printer.
- Print history: `PrintArchive`, `PrintLogEntry`, queue/batch, project/BOM.
- Files: `LibraryFolder`, `LibraryFile`, pending uploads, archive source/timelapse/photos.
- Materials: `Spool`, assignments, catalog, K-profiles, usage history, filament SKU, color catalog, Spoolman mappings.
- Integrations: settings, smart plugs/energy snapshots, notification providers/log/templates/live activity, backup configs/logs, external links.

Các relationship/cascade đáng chú ý: archive thuộc printer/project nhưng printer có thể null; project delete archive `SET NULL`; printer quan hệ archive/maintenance/K-profile/AMS history có cascade delete-orphan; archive deletion có soft-delete `deleted_at` để giữ thống kê trừ khi hard-delete.

## 8. Frontend architecture

- Entry: `frontend/src/main.tsx` -> `App.tsx`.
- Providers: `ThemeProvider`, `ToastProvider`, `QueryClientProvider`, `AuthProvider`, `ColorCatalogProvider`, `SliceJobTrackerProvider`.
- Router: React Router với `basename` từ `appBasePath()`; protected layout bọc WebSocket; camera/overlay là standalone; setup/login có guard riêng; settings/groups/makerworld có permission guard.
- Data: `frontend/src/api/client.ts` là HTTP client tập trung; TanStack Query cache/invalidation; WebSocket cập nhật trực tiếp các query status.
- UI domains: printer dashboard (`PrintersPage`), archives/library, queue/stats, projects, inventory/spools, profiles/slicer, camera, maintenance, notifications, settings/auth, farm command center/monitor.
- i18n: `frontend/src/i18n`, locale `en` là baseline; scripts kiểm tra parity.
- Build CSS/assets: Tailwind/PostCSS/Vite; assets public/static và `gcode_viewer` được phục vụ riêng.

Frontend hotspot lớn: `PrintersPage.tsx`, `ArchivesPage.tsx`, `SettingsPage.tsx`, `FileManagerPage.tsx`, `InventoryPage.tsx`; ưu tiên tìm component/hook/test liên quan trước khi sửa trực tiếp.

## 9. Storage, files và deployment

- Docker Compose là đường khuyến nghị; Linux dùng `network_mode: host` cho discovery/camera/MQTT/FTP/virtual printer.
- Docker Desktop phải dùng `ports:` và thường add printer thủ công; virtual printer passive FTP cần `VIRTUAL_PRINTER_PASV_ADDRESS`.
- Persistent volumes: `/app/data` (DB/archive/config/backups) và `/app/logs`.
- Production image build frontend ở Node stage, backend ở Python 3.13 stage, copy `static/` và `gcode_viewer/`; image expose web + virtual-printer ports.
- Native install dùng `install/install.sh`; systemd/launchd/update helpers nằm trong `install/` và `deploy/`.
- `/health` là healthcheck; log file tùy `LOG_TO_FILE`/`LOG_DIR`.

## 10. Security invariants

- Auth có thể disabled để backward compatibility; khi enabled, route và frontend guard phải fail closed.
- JWT/password change, MFA/TOTP, OIDC/LDAP, API keys và long-lived tokens có code riêng; không log secret.
- Cloud/orca route có API-key gate; URL safety/SSRF guard ở `_url_safety.py`, `http.py`, service network utils.
- File path guard áp dụng cho archive/library/external roots; không nối path từ user input mà thiếu resolve/allowlist.
- 3MF/XML dùng parser an toàn; upload validation, G-code injection guard và credential redaction có test.
- Virtual-printer updater là boundary đặc biệt: Docker socket chỉ nên nằm ở updater sidecar, token phải dùng qua env secret.
- Khi thêm endpoint mới: xác định auth dependency, permission string, SSRF/path/file exposure, rate/size limit và audit/logging behavior.
- MakerWorld membership: `makerworld:import` là quyền lưu 3MF vào server library (premium); `makerworld:view` cho phép xem và tải trực tiếp qua `POST /makerworld/download` (regular). Direct-download route không ghi `LibraryFile`/folder/archive và phải giữ CDN allowlist + 200 MB cap của service.
- MakerWorld có thể dùng tài khoản Bambu Cloud global (`user_id IS NULL`) hoặc tài khoản cá nhân được admin bật `makerworld_shared`; phạm vi chia sẻ chỉ áp dụng cho MakerWorld, không mở rộng các API Cloud thông thường. MakerWorld ưu tiên token cá nhân rồi mới tới token global/shared theo vùng.

## 11. Test và chất lượng

Backend test ở `backend/tests` (pytest/pytest-asyncio, unit/service/API, migration/security); frontend test ở `frontend/src/__tests__` (Vitest, jsdom, Testing Library, MSW). CI (`.github/workflows/ci.yml`) chạy ruff, pip-audit, pytest shard, eslint, TypeScript, Vitest/i18n, Vite build và Docker tests/build.

Lệnh thường dùng:

```powershell
# Backend
python -m pytest backend/tests -q
ruff check backend/
ruff format --check backend/

# Frontend
cd frontend
npm ci
npm run lint
npx tsc --noEmit
npm run test:run
npm run build
```

Root scripts `test_backend.sh`, `test_frontend.sh`, `test_all.sh`, `test_docker.sh`, `test_security.sh` là wrapper/CI-oriented; đọc script trước khi dùng trong môi trường Windows.

## 12. Change playbook

### Thêm/chỉnh tính năng printer

1. Xác định provider/capability và contract trong `printer_providers/base.py`.
2. Cập nhật model/schema/route nếu dữ liệu persistent thay đổi.
3. Sửa provider + `PrinterManager` callback/status normalization.
4. Xem lifecycle callback trong `main.py`, scheduler/queue nếu ảnh hưởng print.
5. Cập nhật frontend API/type/page và WebSocket nếu realtime.
6. Thêm unit/provider/API/UI test và chạy test tối thiểu liên quan.

### Thêm field database

1. Model + `init_db` import.
2. Migration idempotent cho SQLite và PostgreSQL.
3. Pydantic schema/serialization và default/backfill.
4. Route/service/frontend/test.
5. Kiểm tra fresh DB, existing DB, restart và backup/restore.

### Sửa archive/library/file

Đọc `archive.py`, route tương ứng, path guard, 3MF helpers, thumbnail/timelapse và các test `test_*path_guard*`, `test_archive_*`, `test_library_*` trước. Kiểm tra soft-delete, duplicate hash, source files và stats semantics.

### Sửa UI realtime

Đọc `api/client.ts`, query key hiện hữu, `useWebSocket.ts`, `ToastContext`/`SliceJobTrackerContext`; tránh invalidate hàng loạt ngay trong message burst. Kiểm tra desktop/mobile và test event ordering.

## 13. Inventory và lệnh tái lập snapshot

```powershell
rg --files -g '!node_modules' -g '!vendor' -g '!dist' -g '!build' -g '!coverage'
Get-ChildItem backend/app -Recurse -File
Get-ChildItem frontend/src -Recurse -File
rg -n "include_router|APIRouter\(" backend/app/api/routes -g '*.py'
rg -n "@(router|app)\.(get|post|put|patch|delete|websocket)" backend/app -g '*.py'
rg -n "Route path=|createBrowserRouter|BrowserRouter" frontend/src -g '*.{ts,tsx}'
```

Khi bắt đầu phiên mới, đọc file này và `docs/printbuddy-codebase-index.md`, sau đó dùng `rg` để mở đúng route/service/model/test thay vì bắt đầu từ component ngẫu nhiên.

## 14. Known caveats

- `backend/app/main.py` rất lớn và là coordinator; nhiều domain callback vẫn tập trung ở đây, nên thay đổi nhỏ có thể ảnh hưởng restart recovery, notifications, archive và Spoolman.
- Provider abstraction đang tiến hóa: không được suy ra capability chỉ từ `PrinterClientProtocol`.
- Một số tài liệu README còn mô tả trạng thái phát triển cũ; ưu tiên code, test, compose và route registry hiện tại.
- Không có Alembic history riêng; migration nằm trong code, vì vậy mọi schema change cần test trên DB cũ và DB mới.
- Workspace hiện không có `.git` ở root được cung cấp cho phiên này; không dùng trạng thái Git làm bằng chứng thay đổi chưa commit.

