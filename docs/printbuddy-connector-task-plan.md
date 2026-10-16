# Task plan triển khai Printbuddy Connector

Ngày lập: 2026-10-16  
Tài liệu nguồn: [`printbuddy-connector-implementation-plan.md`](printbuddy-connector-implementation-plan.md)  
Trạng thái: Đang triển khai Phase 0-1; các task chưa hoàn tất vẫn giữ `TODO` hoặc `DOING`.

Tài liệu này chuyển kế hoạch kiến trúc thành các task có thể giao và nghiệm thu. Không thay đổi phạm vi kiến trúc đã chốt: Connector là tiến trình độc lập, kết nối outbound WSS/TLS, không mở cổng Internet vào LAN người dùng, hỗ trợ direct mode song song với connector mode.

## 1. Quy ước triển khai

### Trạng thái task

- `TODO`: chưa bắt đầu.
- `DOING`: đang thực hiện.
- `BLOCKED`: có phụ thuộc hoặc quyết định chưa chốt.
- `DONE`: đã có code, test và tài liệu cần thiết.

### Definition of Done chung

Một task chỉ được đánh dấu `DONE` khi:

1. Có code/schema/tài liệu đúng phạm vi task.
2. Có test phù hợp ở mức unit, integration hoặc E2E.
3. Không làm thay đổi hành vi direct mode nếu task chưa ghi rõ.
4. Secret không xuất hiện trong log, response lỗi, metric hoặc support bundle.
5. Đã cập nhật API type, i18n và tài liệu vận hành nếu có thay đổi giao diện/API.
6. Lệnh kiểm tra liên quan chạy đạt; lỗi môi trường phải được ghi rõ trong PR/task.

### Quyết định phạm vi bản đầu

- Hỗ trợ một Printbuddy app instance; chưa tuyên bố hỗ trợ nhiều replica.
- Connector bản đầu ưu tiên Python, đóng gói độc lập và không import `backend.app`.
- Giai đoạn đầu chỉ snapshot camera; live stream và firmware để sau.
- `connection_mode=direct` là mặc định và phải được backfill cho dữ liệu cũ.
- Không có generic TCP tunnel, remote shell, firmware update không xác nhận hoặc fallback âm thầm từ connector sang IP direct.

## 2. Bảng phụ thuộc cấp giai đoạn

| Giai đoạn | Mục tiêu | Phụ thuộc | Kết quả kiểm chứng |
|---|---|---|---|
| G0 | inventory và contract | Không | Schema/protocol fixture và threat model được duyệt |
| G1 | enrollment, gateway, quản lý Connector | G0 | Connector enroll/reconnect/heartbeat/revoke |
| G2 | discovery và transport nền | G1 | Thêm máy in từ LAN qua Connector |
| G3 | trạng thái và điều khiển | G2 | Dashboard/print lifecycle chạy qua Connector |
| G4 | file transfer | G3 | Gửi/nhận file lớn theo streaming |
| G5 | camera và capability nâng cao | G3, G4 một phần | Snapshot, capability/error rõ ràng |
| G6 | phát hành và vận hành | G1-G5 | Package, upgrade, rollback, pilot |

## 3. Giai đoạn G0 — khảo sát và chốt contract

### CON-001 — Inventory call site mạng nội bộ

- **Trạng thái:** `TODO`
- **Phụ thuộc:** Không
- **Mục tiêu:** lập danh sách mọi nơi backend đang dùng `ip_address`, `access_code`, MQTT, FTPS, camera và file path trực tiếp.
- **Phạm vi đọc:** `backend/app/services/bambu_mqtt.py`, `bambu_ftp.py`, `printer_manager.py`, `background_dispatch.py`, `camera*.py`, `firmware*.py`, `layer_timelapse.py`, `printer_diagnostic.py`, route `printers.py`, `camera.py`, `firmware.py`, `print_queue.py`, `archive*` và `main.py`.
- **Đầu ra:** bảng call site gồm provider, capability, timeout, retry, side effect, permission hiện tại và transport dự kiến.
- **Tiêu chí hoàn thành:** không còn call site chưa phân loại; đánh dấu rõ các call có thể chuyển qua RPC và các call cần capability riêng.
- **Kiểm tra:** script inventory bằng `rg`; review thủ công các kết quả.

### CON-002 — Chốt contract protocol v1

- **Trạng thái:** `DOING`
- **Phụ thuộc:** CON-001
- **Mục tiêu:** định nghĩa envelope dùng chung cho enrollment, handshake, heartbeat, command, result, event, error và file transfer metadata.
- **Đầu ra dự kiến:** package schema dùng chung hoặc `connector/protocol/`; JSON Schema/Pydantic models có `schema_version`, `message_id`, `connector_id`, `sent_at`, `type`, `payload`.
- **Quy tắc:** giới hạn kích thước frame/payload; enum command allowlist; deadline; idempotency key; sequence/snapshot; mã lỗi chuẩn hóa.
- **Tiêu chí hoàn thành:** có fixture hợp lệ/không hợp lệ và test round-trip; protocol không chứa token, access code hoặc file content.

### CON-003 — Chốt auth handshake và vòng đời credential

- **Trạng thái:** `DOING`
- **Phụ thuộc:** CON-002
- **Mục tiêu:** quyết định enrollment token một lần, TTL 5-10 phút, token dài hạn sau enrollment, rotate/revoke, nonce/challenge và cách xác thực WSS.
- **Đầu ra:** sequence diagram; threat model ngắn; quy tắc rate limit, replay protection, phiên đồng thời và revoke hiện tại.
- **Tiêu chí hoàn thành:** security review xác nhận không đưa token vào query string, không log token thô, và revoke chặn reconnect.

### CON-004 — Chốt file staging và offline policy

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-002, CON-003
- **Mục tiêu:** chốt TTL URL, one-time use, size/hash, retry/resume, quota, cleanup và hành vi khi Connector offline.
- **Đầu ra:** state machine cho command (`queued` → `sent` → `accepted` → `running` → `succeeded`/`failed`/`expired`/`delivery_unknown`) và bảng policy từng lệnh nguy hiểm.
- **Tiêu chí hoàn thành:** có quy tắc rõ không chạy lệnh hết hạn và không tự retry lệnh start/stop/firmware khi delivery không xác định.

### CON-005 — Tạo test harness và fake Connector

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-002
- **Mục tiêu:** có fake WSS Connector để test server độc lập với máy in thật.
- **Phạm vi:** connect/disconnect, heartbeat, command ack/result, event snapshot, delay, frame lỗi, reconnect và version mismatch.
- **Tiêu chí hoàn thành:** harness chạy được trong backend test suite và có thể mô phỏng Connector offline trong cùng test.

## 4. Giai đoạn G1 — quản lý Connector và gateway

### CON-101 — Model và migration Connector

- **Trạng thái:** `DONE` (model/migration cơ bản đã triển khai; cần bổ sung migration upgrade test riêng)
- **Phụ thuộc:** CON-003
- **Phạm vi code:** model mới dưới `backend/app/models/`, đăng ký trong `backend/app/models/__init__.py`/`database.py`, migration trong `backend/app/core/database.py`.
- **Dữ liệu:** `id`, `public_id`, `owner_user_id`, `name`, `status`, `version`, `platform`, `last_seen_at`, `created_at`, `updated_at`, public-key/certificate hash, credential hash/version, `revoked_at`, disconnect reason đã khử secret.
- **Tiêu chí hoàn thành:** migration idempotent chạy trên SQLite và PostgreSQL; index/FK/unique constraint rõ; dữ liệu cũ không bị thay đổi.
- **Test:** fresh DB, upgrade DB có dữ liệu, rollback/khởi động lại.

### CON-102 — Model enrollment token và command ledger

- **Trạng thái:** `DOING` (enrollment ledger đã triển khai; command ledger để trước khi có command queue)
- **Phụ thuộc:** CON-101, CON-002
- **Phạm vi:** `connector_enrollments`, `connector_commands` hoặc tên tương đương theo convention repo.
- **Quy tắc:** chỉ lưu hash token; one-time/expiry/used-at; command payload đã validate nhưng không có credential/file content; index theo connector/printer/status/deadline.
- **Tiêu chí hoàn thành:** duplicate idempotency key xử lý deterministic; cleanup record quá hạn có policy.

### CON-103 — Permission và ownership policy

- **Trạng thái:** `DOING` (permission và ownership route đã triển khai; còn hoàn thiện audit/rate-limit)
- **Phụ thuộc:** CON-101
- **Phạm vi:** `backend/app/core/permissions.py`, group seed, dependency auth/permission, audit log.
- **Quyền tối thiểu:** `connectors:read`, `connectors:create`, `connectors:update`, `connectors:revoke`, `connectors:discover`, `connectors:control`; quyền printer/file/camera vẫn tách riêng.
- **Tiêu chí hoàn thành:** admin bypass theo convention hiện có; user chỉ thấy Connector thuộc owner/group được cấp; không lộ IP nội bộ/access code.
- **Test:** admin, owner, group member, user không quyền, inactive user, cross-owner access.

### CON-104 — API enrollment và quản lý Connector

- **Trạng thái:** `DOING` (enrollment/list/get/rename/revoke đã triển khai; còn hoàn thiện API command/audit)
- **Phụ thuộc:** CON-101, CON-102, CON-103
- **Phạm vi:** route/schema/service mới; đăng ký router trong `backend/app/main.py` hoặc router registry hiện hành.
- **API dự kiến:**
  - `POST /api/v1/connectors/enrollments`
  - `GET /api/v1/connectors`
  - `GET /api/v1/connectors/{id}`
  - `PATCH /api/v1/connectors/{id}`
  - `POST /api/v1/connectors/{id}/revoke`
  - `GET /api/v1/connectors/{id}/commands/{command_id}`
- **Tiêu chí hoàn thành:** response không trả token thô sau lần tạo; revoke idempotent; lỗi owner/permission/expiry dùng mã ổn định; audit đầy đủ.

### CON-105 — Connector Gateway WSS

- **Trạng thái:** `DOING` (auth/heartbeat/session registry đã triển khai; còn rate-limit/metrics và integration WSS test)
- **Phụ thuộc:** CON-002, CON-003, CON-104
- **Phạm vi:** route riêng `/api/v1/connectors/ws`, service session registry, giới hạn frame/connection/rate.
- **Luồng:** TLS termination theo deployment; auth header hoặc auth frame chống replay; handshake version; heartbeat; close reason; revoke kiểm tra ở mỗi frame quan trọng.
- **Tiêu chí hoàn thành:** reconnect backoff do client; server timeout offline; một Connector không có hai session active ngoài policy; exception không làm chết app.
- **Test:** auth đúng/sai, nonce/replay, frame quá lớn, version mismatch, heartbeat timeout, revoke khi đang connected.

### CON-106 — Connector prototype độc lập

- **Trạng thái:** `DOING` (prototype enrollment/WSS/heartbeat/reconnect và bounded discovery đã triển khai; còn packaging/service)
- **Phụ thuộc:** CON-002, CON-003, CON-005
- **Phạm vi mới:** thư mục `connector/` hoặc package độc lập; không import `backend.app`.
- **Chức năng v1:** đọc config server URL, enrollment token; enroll; lưu credential/key an toàn; WSS reconnect; heartbeat; log redaction; shutdown sạch.
- **Tiêu chí hoàn thành:** chạy được local bằng Python; fake Connector test qua server; không mở listener inbound; hỗ trợ Windows/Linux runtime.

### CON-107 — UI Settings → Connectors

- **Trạng thái:** `DONE` (Settings → Connectors đã có enrollment code một lần, danh sách trạng thái, đổi tên và thu hồi)
- **Phụ thuộc:** CON-104, CON-105
- **Phạm vi dự kiến:** `frontend/src/pages/SettingsPage.tsx` hoặc component tab riêng, `frontend/src/api/client.ts`, i18n `vi.ts` và locale khác, settings search/router.
- **Chức năng:** tạo enrollment, hiển thị mã/QR một lần và TTL, danh sách Connector, online/offline/version/platform, rename, revoke, copy/download hướng dẫn cài.
- **Tiêu chí hoàn thành:** loading/error/empty/revoked states; không render credential; kiểm tra quyền UI chỉ để trải nghiệm, backend vẫn enforce.
- **Test:** API mock, permission visibility, expired enrollment, revoke confirmation, i18n parity.

### CON-108 — Observability gateway

- **Trạng thái:** `DONE` (gateway counters và Prometheus metrics đã bổ sung; không xuất credential/IP nội bộ)
- **Phụ thuộc:** CON-105
- **Phạm vi:** structured logs, metrics, health fields và redaction filter hiện có.
- **Metric tối thiểu:** active sessions, heartbeat age, auth failures, reconnects, command latency/failure, frame limit hits.
- **Tiêu chí hoàn thành:** support bundle không có token/access code/private key; log correlation dùng message/connector ID không dùng secret.

## 5. Giai đoạn G2 — discovery và transport nền

### CON-201 — Bổ sung connection mode cho Printer

- **Trạng thái:** `DONE` (model/schema/migration/API và form thêm/sửa máy in đã hỗ trợ `direct`/`vpn`/`connector`; mode connector không probe từ backend)
- **Phụ thuộc:** CON-101
- **Phạm vi:** `backend/app/models/printer.py`, `schemas/printer.py`, routes/printer tests, migration.
- **Field:** `connection_mode` (`direct`/`vpn`/`connector`), `connector_id`, host/IP LAN chỉ Connector dùng, health timestamp/last agent status.
- **Quy tắc:** một printer chỉ có tối đa một Connector active; mode direct hiện tại được backfill; chuyển mode phải kiểm tra quyền và connectivity.
- **Tiêu chí hoàn thành:** API response không lộ credential; direct create/update vẫn giữ behavior cũ.

### CON-202 — PrinterTransport abstraction

- **Trạng thái:** `DOING` (đã thêm transport boundary, Connector discovery adapter và status adapter cho REST status; các capability control/file vẫn chưa nối)
- **Phụ thuộc:** CON-002, CON-201
- **Phạm vi dự kiến:** `backend/app/services/printer_transport.py`, direct/connector implementation, factory/provider integration.
- **Interface tối thiểu:** `test_connection`, `connect`, `disconnect`, `request_status`, `send_command`, `list_files`, `upload_file`, `download_file`, `delete_file`, `get_snapshot`, `diagnostic`.
- **Tiêu chí hoàn thành:** domain routes không tự mở socket bằng `printer.ip_address`; direct adapter gọi code cũ; connector adapter chỉ gửi typed RPC; capability thiếu trả `capability_unavailable`. Hiện discovery đã đi qua `ConnectorPrinterTransport`; phần provider operations còn lại tiếp tục ở CON-301+.

### CON-203 — Discovery command qua Connector

- **Trạng thái:** `DOING` (đã có protocol v1, API đồng bộ, gateway request/response, TCP scanner private LAN và typed verify/status RPC; đã có verify Bambu MQTT/Moonraker HTTP/PrusaLink HTTP; frontend Add Printer đã có chọn Connector, quét subnet và chọn endpoint; còn command ledger/query trạng thái dài hạn và application-level credential envelope)
- **Phụ thuộc:** CON-105, CON-201, CON-202
- **API:** `POST /api/v1/connectors/{id}/discoveries`, query trạng thái/result.
- **Bảo vệ:** CIDR/port allowlist, timeout, concurrency, max host, không nhận URL tùy ý; chỉ user có `connectors:discover`.
- **Connector:** scanner endpoint và typed `printer.verify/status` theo provider/port, trả result đã lọc. Provider verify nhận secret ngắn hạn qua WSS/TLS, không lưu hoặc trả lại secret; discovery/status không nhận secret.
- **Tiêu chí hoàn thành:** discovery không quét Internet; kết quả phân biệt reachable/protocol/auth/capability. Nền tảng hiện tại báo TCP reachable, status snapshot tối thiểu và verify provider cho Bambu/Moonraker/PrusaLink; credential envelope cấp ứng dụng và command ledger vẫn còn.

### CON-204 — Add printer qua Connector

- **Trạng thái:** `DOING` (route tạo printer Connector đã bắt buộc typed verify provider; frontend wizard đã chọn Connector → discovery result → điền endpoint → verify trước khi gọi create; credential envelope và test UI chuyên biệt còn lại)
- **Phụ thuộc:** CON-201, CON-203
- **Phạm vi:** route `printers.py`, schema/UI `PrintersPage.tsx`, wizard chọn Connector → discovery result → credential → verify.
- **Tiêu chí hoàn thành:** verify qua Connector trước khi lưu; binding printer-connector atomic; lỗi từng capability hiển thị riêng; test fake printer. Hiện đã chặn lưu nếu provider handshake thất bại; UI wizard và application-level credential protection vẫn chưa hoàn tất.

### CON-205 — Đóng gói discovery Connector

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-106, CON-203
- **Phạm vi:** dependency connector, config file/env, Windows/Linux service, Docker image cơ bản.
- **Tiêu chí hoàn thành:** chạy từ mạng khác chỉ cần outbound HTTPS/WSS; tài liệu firewall nêu rõ các kết nối Connector → printer trong LAN và passive FTP caveat.

## 6. Giai đoạn G3 — trạng thái và điều khiển

### CON-301 — MQTT session và telemetry snapshot

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-202, CON-204, CON-205
- **Phạm vi:** Connector dùng logic Bambu MQTT đã tách/đóng gói; server event mapper vào `PrinterManager`/websocket callback.
- **Quy tắc:** snapshot trước event sequence; coalesce telemetry; stale status khi Connector offline; không replay event cũ vô hạn.
- **Tiêu chí hoàn thành:** dashboard nhận trạng thái giống direct mode; reconnect gửi snapshot mới; sequence gap có recovery.

### CON-302 — Command queue và state machine

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-102, CON-301
- **Phạm vi:** command service/dispatcher, persistence, session registry, timeout/cancel.
- **Lệnh ban đầu:** start/pause/resume/stop và lệnh Bambu an toàn đã có trong provider; allowlist theo capability.
- **Tiêu chí hoàn thành:** server ghi DB trước khi gửi; duplicate command deterministic; `delivery_unknown` không tự replay lệnh nguy hiểm.

### CON-303 — Tích hợp print lifecycle

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-301, CON-302
- **Phạm vi:** `backend/app/main.py`, `background_dispatch.py`, scheduler/queue/archive/notification/WebSocket.
- **Tiêu chí hoàn thành:** callback archive, notification, runtime, queue và live UI chạy khi printer ở connector mode; direct regression không đổi.

### CON-304 — Offline/reconnect behavior

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-302, CON-303
- **Mục tiêu:** trạng thái UI “Connector offline”, không giả lập printer disconnected; xử lý lệnh pending/expired theo policy.
- **Test:** rút WSS, hết deadline, reconnect giữa command, mất event, revoke khi offline rồi reconnect.

## 7. Giai đoạn G4 — file transfer

### CON-401 — File staging service

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-004, CON-302
- **Phạm vi:** service tạo one-time URL/token cho file server và upload staging Connector; path guard/storage quota hiện có phải được tái sử dụng.
- **Tiêu chí hoàn thành:** token gắn owner/printer/connector/file/action/expiry; content length/hash bắt buộc; cleanup khi hết TTL; không truyền file trong WebSocket.

### CON-402 — Server → Connector → printer upload

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-401, CON-205
- **Phạm vi:** `bambu_ftp.py`, `background_dispatch.py`, print queue, upload routes.
- **Luồng:** Connector stream HTTPS, kiểm tra size/hash, upload FTPS LAN, trả result; cache tạm có quota/TTL.
- **Tiêu chí hoàn thành:** file lớn không buffer toàn bộ RAM; checksum mismatch/FTPS passive failure báo lỗi riêng; retry không tạo bản upload sai.

### CON-403 — Printer → server archive/timelapse download

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-401, CON-402
- **Phạm vi:** archive service, timelapse/layer capture, library path guard.
- **Tiêu chí hoàn thành:** server xác thực owner/printer, hash/size/content trước khi lưu; không cho Connector chọn path đích tùy ý; cleanup khi disconnect.

### CON-404 — File operation capability và UI

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-402, CON-403
- **Phạm vi:** list/download/delete file routes, printer/file components, typed API client, i18n.
- **Tiêu chí hoàn thành:** UI hiển thị capability unavailable, progress/error/retry; quyền file kiểm tra độc lập với quyền control.

## 8. Giai đoạn G5 — camera và capability nâng cao

### CON-501 — Snapshot camera qua Connector

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-301, CON-202
- **Phạm vi:** `backend/app/api/routes/camera.py`, camera services, Connector snapshot RPC.
- **Tiêu chí hoàn thành:** snapshot có timeout/size limit; RTSP credential không ra frontend; permission và binding printer/connector được kiểm tra.

### CON-502 — Live camera session (sau pilot snapshot)

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-501, security review
- **Phạm vi:** token ngắn hạn gắn user/printer/connector/browser session; TTL, bitrate/session limit, cleanup khi tab đóng.
- **Tiêu chí hoàn thành:** không có TCP tunnel tùy ý; reconnect và revoke kết thúc session.

### CON-503 — Diagnostics và AMS/capability nâng cao

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-301, CON-404
- **Phạm vi:** diagnostics, AMS, firmware/advanced command theo từng provider/capability.
- **Tiêu chí hoàn thành:** từng capability có timeout, permission, test và UI lỗi riêng; firmware chỉ triển khai sau policy xác nhận.

## 9. Giai đoạn G6 — phát hành và vận hành

### CON-601 — Version compatibility và migration policy

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-002, CON-106
- **Phạm vi:** protocol min/max, server compatibility matrix, graceful version mismatch, upgrade notice.
- **Tiêu chí hoàn thành:** hỗ trợ ít nhất hai phiên bản Connector gần nhất hoặc nêu rõ policy; Connector cũ không bị loop reconnect vô hạn.

### CON-602 — Package Windows/Linux/Docker

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-205, CON-601
- **Đầu ra:** Windows service/installer, Linux systemd, Docker image/compose sample, config/secret storage guide.
- **Tiêu chí hoàn thành:** cài mới, restart, uninstall/revoke và log collection hoạt động; không yêu cầu cài toàn bộ Printbuddy server.

### CON-603 — Signed update và rollback

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-602
- **Phạm vi:** manifest tin cậy/chữ ký, checksum, staged update, rollback khi health check thất bại.
- **Tiêu chí hoàn thành:** update không chạy binary không xác thực; có hướng dẫn rollback thủ công.

### CON-604 — Health dashboard và support bundle

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-108, CON-601
- **Tiêu chí hoàn thành:** hiển thị last seen/version/capability/error; support bundle có correlation ID và đã khử token/access code/private key.

### CON-605 — Pilot và runbook vận hành

- **Trạng thái:** `TODO`
- **Phụ thuộc:** CON-602, CON-604, các exit criteria G3/G4
- **Kịch bản:** VPS + Connector Linux Docker ở mạng nhà khác; Connector Windows; không mở inbound router; add printer; status; pause/resume; 3MF; archive; offline/reconnect; revoke.
- **Tiêu chí hoàn thành:** có biên bản kết quả, giới hạn đã biết, kế hoạch rollback và hướng dẫn support.

## 10. Ma trận kiểm thử bắt buộc

| Nhóm | Case tối thiểu | Nơi đặt |
|---|---|---|
| Protocol | schema, frame limit, version, duplicate ID, replay | `backend/tests/unit/connector/`, `connector/tests/` |
| Auth | enroll expiry/reuse, wrong owner, revoke, rotate, reconnect | backend integration |
| Gateway | heartbeat timeout, concurrent session, rate/size limit | backend integration |
| Permission | owner/group/admin/cross-owner/inactive user | backend API tests |
| Printer | direct + connector cùng server, binding, discovery, diagnostics | backend integration |
| State | snapshot/event ordering, stale, command transitions, delivery unknown | service tests |
| File | URL expiry, checksum, partial transfer, quota, cleanup, path guard | service/integration |
| Camera | snapshot timeout/permission, live TTL nếu có | camera integration |
| Database | fresh/upgrade SQLite và PostgreSQL | migration CI |
| E2E | VPS/LAN khác, rút mạng, restore, revoke | `tests/e2e/` hoặc runbook |
| Security | secret redaction, no inbound listener, no arbitrary host/tunnel | security tests/manual |

## 11. Thứ tự thực hiện đề xuất

1. `CON-001` → `CON-005`: chốt inventory, protocol, security và fake Connector.
2. `CON-101` → `CON-108`: hoàn thiện quản lý Connector, chưa đụng điều khiển máy in.
3. `CON-201` → `CON-205`: chuyển model/transport/discovery và add printer.
4. `CON-301` → `CON-304`: status, command, callbacks, offline policy.
5. `CON-401` → `CON-404`: staging và file transfer.
6. `CON-501` → `CON-503`: snapshot trước, live/capability sau.
7. `CON-601` → `CON-605`: packaging, update, dashboard, pilot.

Không bắt đầu CON-301 trước khi CON-202 có direct adapter và fake Connector; không bắt đầu CON-402 trước khi CON-401 có staging token/path guard; không đưa live camera/firmware vào pilot đầu tiên.

## 12. Checklist trước khi bắt đầu coding

- [ ] Xác nhận hỗ trợ một app instance trong bản đầu.
- [ ] Chọn tên package/thư mục Connector và cách phát hành Python/compiled binary.
- [ ] Chốt kiểu auth: bearer sau TLS hay challenge ký bằng public key.
- [ ] Chốt secret store theo Windows/Linux/Docker.
- [ ] Chốt retention `connector_commands`, audit và telemetry.
- [ ] Chốt CIDR/port allowlist cho discovery.
- [ ] Chốt file size/quota/TTL và passive FTP support.
- [ ] Xác nhận policy offline cho từng command nguy hiểm.
- [ ] Tạo fixture máy in giả và fake WSS Connector trong CI.
- [ ] Chốt UI tab Settings → Connectors và permission names trước khi thêm locale.

## 13. Lệnh kiểm tra theo loại thay đổi

Backend:

```powershell
cd backend
ruff check app tests
pytest -q
```

Frontend:

```powershell
cd frontend
npm run check:i18n
npx tsc --noEmit -p tsconfig.app.json
npm run lint
npm run test -- --run
npm run build
```

Protocol/Connector:

```powershell
pytest -q connector/tests backend/tests/unit/connector backend/tests/integration/connector
```

Trước pilot cần kiểm tra thủ công WSS/TLS, không có inbound listener, firewall LAN-to-printer, reconnect, revoke và support bundle redaction.

## 14. Rủi ro cần theo dõi trong task board

- Số lượng call site direct lớn hơn inventory dự kiến: không gộp transport refactor vào một PR quá lớn.
- SQLite migration giữ lock lâu: test DB có dữ liệu thật và backup trước upgrade.
- Connector bị dùng làm proxy vào LAN: chỉ allowlist command, ràng buộc printer binding và từ chối host/URL tùy ý.
- Credential lọt qua exception/diagnostic: thêm test redaction trước khi bật pilot.
- FTPS passive mode qua mạng nhà: ghi rõ giới hạn, không hứa chỉ cần cổng 443 cho đường Connector → printer.
- Nhiều worker/replica: giữ single-instance ở v1, nhưng không hard-code thiết kế khiến sau này không thêm broker/lease được.

