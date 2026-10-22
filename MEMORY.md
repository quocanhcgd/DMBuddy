# Printbuddy Working Memory

Đây là điểm vào ngắn cho các phiên điều chỉnh tiếp theo. Bản mô tả đầy đủ nằm ở:

- [`docs/printbuddy-system-memory.md`](docs/printbuddy-system-memory.md): kiến trúc, runtime, dữ liệu, luồng sự kiện, tích hợp, rủi ro và quy trình sửa.
- [`docs/printbuddy-codebase-index.md`](docs/printbuddy-codebase-index.md): bản đồ thư mục, phạm vi mã nguồn, route/module chính và lệnh kiểm tra.
- [`docs/flashforge-integration-reference.md`](docs/flashforge-integration-reference.md): đặc tả giao thức FlashForge tham khảo từ Print Farm Controller.
- [`docs/flashforge-integration-plan.md`](docs/flashforge-integration-plan.md): kế hoạch triển khai theo phase, tiêu chí nghiệm thu và nhật ký tiến trình hỗ trợ FlashForge.
- [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md): khảo sát và kế hoạch kiểm chứng K3 qua Moonraker trước khi thêm tính năng riêng cho nozzle changer.

## Creality K3 checkpoint (2026-10-22)

- Đã thêm `Creality K3` vào danh mục `Creality Klipper`; Moonraker discovery dò mặc định `7125,80,4408`, chỉ nhận `server/info` có JSON Moonraker. Scanner dùng một HTTP client giới hạn 32 kết nối, batch 32.
- Người dùng xác nhận subnet `192.168.0.0/24`. Quét live hoàn tất `254/254`, tìm thấy K3 `192.168.0.158` qua `7125`; gọi trực tiếp `:4408/server/info` cũng trả HTTP 200 Moonraker JSON. Có Moonraker khác ở `.38`. `hardware_verified=true` cho reachability/discovery; chưa xác minh chu trình in.
- Đã quét lại ngay trên Add Printer UI: kết quả `192.168.0.158` xuất hiện; chọn kết quả điền IP, Moonraker URL và model `K3`. Sửa lỗi UI giữ thông báo no-results sau khi chọn endpoint bằng cách reset `hasScanned` và progress. TypeScript đạt; Add Printer component test không collect được do conflict ESM/CommonJS hiện hữu trong `react-router-dom`/`react-router`.
- Ảnh model Creality hiện đã ánh xạ cho Ender-3 family, Ender-5 Plus, CR-10S Pro family, K1/K1C/K2 Plus và K3. K3 artwork lấy từ trang sản phẩm chính thức của Creality; các ảnh K3 lưu tại `frontend/public/img/printers/creality-k3.png` và `static/img/printers/creality-k3.png`.
- Scanner unit `12 passed`, Ruff đạt. K3 model catalog trước đó `1 passed`, compileall, TypeScript và i18n parity đạt. Add Printer page test trước đó không collect được do lỗi ESM/CommonJS `react-router-dom`/`react-router`.
- K3 nozzle changer, camera, auth, ordinary print lifecycle và contract đổi nozzle vẫn chưa xác minh. Bước tiếp: enroll qua Add Printer, kiểm tra Klipper objects và chu trình G-code thông thường có giám sát; nghiên cứu nozzle changer riêng theo slicer output/API thực. Chi tiết: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md).
- Moonraker provider đã có status, file list/upload/start, pause/resume/cancel, nhiệt độ/fan và webcam discovery. Không áp dụng macro CFS hoặc camera K2 cho K3.

## FlashForge checkpoint (2026-10-22)

- Phase 4 AD5M direct vẫn `DOING`: status/files/upload/job, nhiệt, fan và camera stream/snapshot đã có code path fake-tested; direct camera dùng proxy/token/fan-out, `hardware_verified=false`. Filtration và calibration độc lập vẫn planned do thiếu state readback.
- Creator 5 Phase 5: direct HTTP status bốn nozzle, recent-file list, nhiệt nozzle/bed, chamber chỉ Pro, material status/config, upload, start, pause/resume/cancel và direct camera proxy đã có precheck/readback phù hợp. `currentSlot` vẫn tách khỏi active tool.
- Material dùng 21 loại và 24 màu allowlist; chỉ đổi khi idle, giữ metadata trường không đổi, slot firmware 1-based, không retry side-effect. Upload `tool_count` 1-4 (mặc định 1), `printNow=false`, Creator5 material-station headers; file start riêng. HTTP recent listing thiếu completeness/size nên upload chỉ được xác nhận tên xuất hiện, không phải integrity.
- Start chỉ nhận file root đang hiện trong recent list và xác nhận status RUNNING + filename. Job control gửi lệnh một lần rồi reconcile status. Camera direct cho AD5M/Creator 5 đi qua proxy/token/fan-out; Connector relay chưa có. Creator 5 Printbuddy-owned queue hiện có editor map logical tool → physical slot và completeness gate; file-local start vẫn không nhận mapping, không suy diễn `toolId` từ `slice_info.config.slot_id`.
- Queue scheduler và background dispatch đã chặn AMS mapping/platform option của Bambu trước upload Creator 5; `gcodeToolCnt` lấy từ các slot filament đã dùng trong `slice_info.config`, fallback 1 khi không có metadata.
- Verification gần nhất: Creator5 + camera-source + contract unit 64; FlashForge camera snapshot/live integration 4; scheduler/background provider-upload tests 14; broader FlashForge/provider protocol selection 114; Ruff đạt. Pydantic namespace warnings hiện hữu. Chưa có firmware/emulator/máy thật; `hardware_verified=false`, evidence `source_inferred`.
- Phase 11 discovery hiện `DOING`: package thuần `flashforge_discovery` đã parse packet modern 276-byte, legacy 140-byte và TCP `~M115`, có 6 unit tests. Parser không biến command port Creator 5 thành TCP capability; chưa bật socket/network discovery.
- Connector Phase 12 discovery/verify/status đã `DOING` cho nhánh FlashForge: UDP/M115 bounded, verify HTTP `/detail`, status `/detail` chuẩn hóa state/progress/filename/temperatures/firmware; credentials chỉ truyền ngắn hạn trong memory. UI Add Printer điền provider/model/serial/HTTP port sau khi chọn endpoint. Nhóm test liên quan đạt 102; chưa có firmware capture.
- Connector upload `delivery_unknown` hiện lấy file listing read-only và báo trạng thái quan sát, completeness/source, nhưng luôn giữ HTTP 504 và `integrity=unverified`; AD5M M661 là complete theo code path, Creator 5 chỉ recent-only, cả hai không có size/hash nên không thể xác nhận upload.
- Connector upload đã bổ sung endpoint guard private-LAN và basename validation ngay tại agent, trước khi mở HTTP request; payload đích/credential của upload được khóa từ `begin`, các phase sau không thể đổi đích. Duplicate begin, chunk order, finish cleanup, abort và TTL/disconnect cleanup đã được rà.
- Error-path audit xác nhận response Connector không trả raw firmware body; exception bất ngờ thành `operation failed`, còn ValueError gửi thông điệp domain đã kiểm soát. Agent tests hiện kiểm tra credential không bị trả lại.
- Connector status telemetry giờ chỉ chấp nhận field allowlist, giới hạn state/filename/firmware, số heater và miền nhiệt/progress; parser cắt string và bỏ số NaN/Inf/out-of-domain. File-list schema vốn đã giới hạn 256 entry, độ dài name/path và 2 MiB upstream body.
- Creator 5 PrintModal editor kiểm tra mapping đủ logical tools/physical slots; một guard dùng chung disable nút và chặn trực tiếp `handleSubmit`, kể cả submit bằng Enter. Kiểm tra mới nhất: backend selected tests `62 passed`, Ruff, TypeScript, build, i18n parity và component test `2 passed`; full Vitest `631 passed, 11 failed` do test cũ kỳ vọng tiếng Anh trong locale vi. Build warning Node `20.12.2` và bundle >3 MiB.
- Queue mapping API integration đã kiểm tra create/update/GET/clear, DB JSON round-trip và từ chối sai printer provider (`3 passed`). Test phát hiện và sửa PATCH serializer bị gọi `model_dump()` trên dict, vốn gây 503. Workspace không có file `.3mf`/`.gcode` slicer thật.
- Verification mới nhất: upload unit + agent phase tests `15 passed` (7 deselected), upload reconciliation route `3 passed`; status/provider + agent unit `27 passed`; typed status RPC integration `1 passed`, printer status route `1 passed`, file-list unit `3 passed`; Ruff đạt. `hardware_verified=false`; không có máy FlashForge thật.
- Bước tiếp: xác minh parser bằng file 3MF/G-code thật từ Creator 5/Orca/FlashPrint, rồi rà upload/start end-to-end và physical smoke Creator 5/Pro khi có máy. AD5M hardware smoke, Connector mapping/camera relay, UDP/M115 firmware capture và filtration evidence còn thiếu. Chi tiết ở [`docs/flashforge-integration-plan.md`](docs/flashforge-integration-plan.md).

## Tóm tắt một câu

Printbuddy là ứng dụng self-hosted quản lý nhiều hệ sinh thái máy in 3D: FastAPI/SQLAlchemy async ở backend, React/Vite/TypeScript ở frontend, WebSocket cho trạng thái trực tiếp, provider boundary cho Bambu/Moonraker/Prusa/Elegoo, và Docker là đường triển khai chính.

## Các điểm phải nhớ khi sửa

1. Backend khởi động từ `backend.app.main:app`; API mặc định có prefix `/api/v1`.
2. SQLite là mặc định (`DATA_DIR/printbuddy.db`), PostgreSQL dùng `DATABASE_URL`; schema và migration được xử lý trong `backend/app/core/database.py`.
3. `backend/app/main.py` chứa lifespan, callback vòng đời print và wiring dịch vụ; thay đổi tại đây có blast radius lớn.
4. Printer-specific code phải đi qua `backend/app/services/printer_providers/` và `PrinterManager`; không giả định mọi provider có MQTT/FTP/AMS.
5. Frontend dùng React Router + TanStack Query; dữ liệu realtime đi qua `/api/v1/ws` và `useWebSocket.ts`, có throttle/debounce để tránh đóng băng UI.
6. File, archive, thumbnail, timelapse và source 3MF đều gắn với đường dẫn trên filesystem; mọi route nhận path phải giữ path guard và không mở rộng root tùy tiện.
7. Auth/permission có cả legacy `role=admin` và group permissions; admin được bypass permission, user thường nhận quyền cộng dồn từ group.
8. Sau thay đổi backend chạy `ruff` và pytest; sau thay đổi frontend chạy lint, typecheck, test và build; thay đổi Docker/deploy cần kiểm tra compose/build.

## Việt hoá

- Locale tiếng Việt nằm ở `frontend/src/i18n/locales/vi.ts`, mã `vi`, tên hiển thị `Tiếng Việt`.
- Locale được đăng ký trong `frontend/src/i18n/index.ts`; danh sách ngôn ngữ của Settings tự hiển thị entry mới.
- Script tái sinh: `frontend/scripts/generate-vietnamese-locale.mjs`; hướng dẫn và phạm vi ở `docs/vietnamese-localization.md`.
- Sau khi sửa catalog chạy `cd frontend; npm run check:i18n; npx tsc --noEmit`.
- Đây là bản dịch máy cần hiệu đính; text hard-code, backend errors, notification templates và định dạng ngày/số chưa nằm trong catalog này.

## Luồng đọc nhanh

`README.md` -> `docs/printbuddy-system-memory.md` -> `backend/app/main.py` -> `backend/app/core/config.py`/`database.py` -> route liên quan -> service -> model/schema -> page/component frontend -> test tương ứng.

## Kế hoạch: MakerWorld User Accounts

Đây là tên tham chiếu cho kế hoạch sẽ triển khai sau.

- Tài khoản MakerWorld là **tài khoản người dùng được tạo trong Printbuddy**, không phải một loại Bambu Cloud account độc lập.
- Người dùng MakerWorld đăng nhập vào Printbuddy bằng cơ chế xác thực hệ thống hiện có.
- WeChat/QQ/access token China chỉ là **connector** gắn với user để truy cập và tải dữ liệu MakerWorld; token không được gửi xuống frontend.
- Nên tạo bảng `makerworld_connectors` gồm `user_id`, `region`, `provider`, token mã hóa, remote user ID, trạng thái và thời điểm xác thực.
- Thêm loại user/nhóm quyền MakerWorld, tối thiểu: `makerworld:view`, `makerworld:import`, `makerworld:storage:read`, `makerworld:storage:write`; không cấp quyền quản lý printer/Bambu Cloud/admin.
- Mỗi user có kho riêng: `data/users/{user_id}/makerworld/{downloads,archives,thumbnails,metadata}`. Không dùng email làm tên thư mục; mọi file/folder phải gắn `owner_user_id` và kiểm tra ownership ở backend.
- `LibraryFile`/`LibraryFolder` cần bổ sung owner và connector liên quan; migration dữ liệu cũ phải gắn vào owner mặc định/admin.
- UI cần có quản trị user/quota/khóa tài khoản và khu vực user để liên kết, kiểm tra connector, xem dung lượng và thư viện riêng.
- Khi resolve/import MakerWorld, request dùng `makerworld_connector_id`; backend tự lấy token, tự chọn endpoint Global/China và lưu file vào kho của user.

Khi người dùng nói “tiếp tục MakerWorld User Accounts”, tiếp tục từ thiết kế này và trước khi code kiểm tra lại model `User`, permission/group, `LibraryFile`, `LibraryFolder` và cơ chế storage hiện tại.

## Quy tắc MakerWorld theo hạng thành viên

- Thành viên cao cấp được cấp `makerworld:import`: có thể lưu 3MF vào thư viện máy chủ, tạo thư mục model và dùng các thao tác Slice/Open in slicer dựa trên file thư viện.
- Thành viên thường chỉ cần `makerworld:view`: được resolve/xem model và gọi `POST /makerworld/download` để tải trực tiếp về thiết bị; endpoint này không tạo `LibraryFile`, folder, thumbnail hay source archive.
- Backend là nơi enforce chính; frontend chỉ ẩn/hiện nút theo quyền. Không coi việc ẩn nút là biện pháp bảo mật.

### Tài khoản Cloud dùng chung cho MakerWorld

- `BambuCloudAccount.makerworld_shared` cho phép admin chia sẻ một tài khoản cá nhân chỉ trong MakerWorld; API Cloud thông thường vẫn chỉ trả tài khoản của chủ sở hữu.
- Tài khoản Cloud global cũ (`user_id IS NULL`, thường sinh ra khi auth disabled) được coi là shared connector cho MakerWorld để các user chỉ có `makerworld:view` vẫn tải được 3MF.
- MakerWorld ưu tiên token cá nhân của user; nếu không có thì dùng tài khoản global/shared phù hợp vùng. Token không bao giờ gửi xuống frontend.

## Quyết định thương hiệu hiển thị: DMbuddy

- Chỉ đổi phần người dùng nhìn thấy sang **DMbuddy**: tiêu đề trang/PWA, logo, màn hình đăng nhập/thiết lập, nhãn cài đặt, thông báo/email và chuỗi giao diện.
- Giữ nguyên toàn bộ định danh kỹ thuật để bảo toàn khả năng tương thích: tên repository/URL GitHub, API route và schema, database/volume, biến môi trường, tên service/container, khóa localStorage, topic/metric/event key, tên file cấu hình và tên module.
- Khi bổ sung giao diện mới, dùng nhãn hiển thị DMbuddy nhưng không đổi các khóa kỹ thuật có tiền tố `printbuddy`.

## Kế hoạch triển khai Printbuddy Connector

- Thiết kế kiến trúc đầy đủ nằm ở [`docs/printbuddy-connector-implementation-plan.md`](docs/printbuddy-connector-implementation-plan.md).
- Backlog task có mã, phụ thuộc, file/module dự kiến, tiêu chí nghiệm thu và lệnh kiểm tra nằm ở [`docs/printbuddy-connector-task-plan.md`](docs/printbuddy-connector-task-plan.md).
- Thứ tự bắt buộc: inventory/protocol/security → enrollment/gateway → discovery/transport → status/control → file transfer → camera/capability → packaging/pilot.
- Đã bắt đầu Phase 0-1: protocol package, model/migration Connector, enrollment API, permission, WSS gateway và prototype heartbeat nằm trong `connector/`.
- Đã hoàn tất UI Phase 1 tại Settings → Connectors: tạo mã enrollment TTL 10 phút (chỉ hiển thị một lần), danh sách online/offline/revoked, version/platform/last seen, đổi tên và thu hồi theo permission; credential dài hạn không xuất hiện trên frontend.
- Gateway đã có observability counters và Prometheus metrics cho active sessions, session starts/replacements/disconnects, send/auth/protocol/frame/heartbeat lỗi; metric chỉ là số tổng hợp, không chứa credential hoặc IP nội bộ.
- Printer đã có `connection_mode` (`direct`/`vpn`/`connector`) và `connector_id`; dữ liệu cũ mặc định `direct`. API và form thêm/sửa máy in kiểm tra Connector còn hoạt động; tạo mới ở connector mode đã verify endpoint qua Connector, không probe IP từ backend.
- Discovery Connector đã có nền tảng v1: `POST /api/v1/connectors/{id}/discoveries` kiểm tra private CIDR/port/timeout, gateway request-response gắn đúng Connector, protocol `discovery.request/result`, và agent scanner TCP giới hạn 256 host/16 port/concurrency 64, không trả credential/banner. Provider verify hiện hỗ trợ Bambu MQTT TLS, Moonraker HTTP/Bearer và PrusaLink HTTP.
- Frontend Add Printer đã nối discovery/verification qua Connector: nhập private subnet, chỉ bật quét khi Connector online, hiển thị endpoint đã lọc, chọn endpoint để điền IP/provider, và bắt buộc verify qua Connector trước khi gửi create. API client có typed methods cho discovery, verify và status; tất cả locale đã bổ sung nhãn Connector.
- REST `GET /printers/{id}/status` đã có nhánh Connector: không gọi `PrinterManager` cục bộ, trả `connector_status`/transport details và dùng typed `printer.status.request`; Connector offline được báo rõ.
- Connector có bộ đóng gói độc lập tại `connector/Dockerfile`, `connector/docker-compose.yml` và `connector/requirements.txt`: Linux dùng host networking, state credential nằm trong named volume non-root, chỉ outbound WSS; README có hướng dẫn Windows/Docker Desktop và quy tắc vận hành.
- Windows được ưu tiên bằng `connector/windows/install-connector-task.ps1`: cài dependency, enroll một lần, lưu state dưới `%LOCALAPPDATA%\Printbuddy\Connector` và đăng ký Task Scheduler chạy khi user đăng nhập; `run-connector.ps1` không lưu enrollment code vào task.
- Có thể đóng gói Connector Windows thành `connector/windows/dist/PrintbuddyConnector.exe` bằng `connector/windows/build-exe.ps1`; installer nhận `-ExecutablePath` để chạy bản self-contained qua Task Scheduler, vẫn giữ Python fallback. Enrollment code chỉ truyền qua environment của tiến trình bootstrap.
- Bản Windows hiện có UI PySide6 tại `connector/windows/printbuddy_connector_app.py`: nhập server URL, đăng nhập tài khoản Printbuddy, xử lý 2FA, tự tạo enrollment code và hiển thị trạng thái/log. Password, JWT và enrollment code không lưu vào đĩa; credential Connector vẫn nằm trong state file riêng. `.exe` mở bình thường là UI, còn `--agent` là chế độ nền cho Task Scheduler.
- Thẻ máy in đã hiển thị route Connector cho cả chế độ compact và expanded: tên Connector (nếu user có quyền xem), mũi tên và IP nội bộ đã bind; không hiển thị credential.
- Discovery route hiện đã đi qua `backend/app/services/printer_transport.py`: `ConnectorPrinterTransport` kiểm tra result/timeout và không fallback âm thầm sang direct; `DirectPrinterTransport` trả `capability_unavailable` cho discovery chưa triển khai. Status/control/file adapters vẫn là phần tiếp theo.
- Đã thêm typed RPC `printer.verify.request/result` và `printer.status.request/result`. Discovery/status không nhận credential; provider verify nhận access code/token chỉ trong request WSS ngắn hạn, xử lý trong memory và không lưu/log/echo. API tạo printer ở `connection_mode=connector` bắt buộc verify trước khi lưu; application-level encryption riêng cho credential và UI wizard discovery → add vẫn chưa hoàn tất.
- Các task Phase 0-1 đã triển khai một phần được đánh dấu `DOING`/`DONE` trong task plan; transport, status/control, file, camera và packaging production vẫn chưa triển khai hoàn chỉnh.

### FlashForge Connector checkpoint — 2026-10-21

- Đã hoàn tất read-only file listing qua Connector bằng RPC `printer.files.request/result`.
- AD5M: TCP M601/M661/M602 có khóa, giới hạn response và fallback HTTP `/gcodeList`; Creator 5/Pro: chỉ HTTP recent list, không mở TCP 8899.
- Backend `ConnectorPrinterTransport.files()` và route `GET /printers/{id}/files` đã dùng credential giải mã trong thời gian gọi, trả entry đã sanitize và completeness/source.
- Test group mới và hồi quy liên quan đạt, gồm route integration Connector file listing; vẫn `source_inferred`, `hardware_verified=false`, chưa có máy thật/emulator.
- Bước tiếp theo: integration route test, sau đó RPC upload/control có streaming và side-effect guard.

### FlashForge Connector upload checkpoint — 2026-10-21

- Đã triển khai upload chunked `begin/chunk/finish` qua Connector và multipart `/uploadGcode` ở LAN.
- Chunk được giới hạn, kiểm tra thứ tự/kích thước, dọn temp file; response không chứa credential. Backend truyền đúng filename đích.
- Connector FlashForge upload hiện chỉ root path và conflict strategy `error`; chưa có resume hoặc rename/delete-replace.
- Verification unit + integration và Ruff/compileall đạt; vẫn `source_inferred`, `hardware_verified=false`, chưa có máy thật/emulator.
- Bước tiếp theo: RPC job control với pre-read status, một side-effect command và readback xác nhận.

### FlashForge Connector control checkpoint — 2026-10-21

- Đã nối RPC `printer.control.request/result` cho start/pause/resume/cancel.
- Connector pre-read `/detail`, gate theo state, gửi một command duy nhất và post-read để xác nhận; backend route Connector không dùng `PrinterManager` cục bộ.
- Start giữ root file và không bật tool mapping/storage; timeout không tự retry side effect.
- Unit/integration/Ruff/compileall đạt; giao thức vẫn `source_inferred`, `hardware_verified=false`, chưa có máy thật/emulator.
- Bước tiếp theo: bounded polling readback và các control nhiệt độ qua Connector, sau đó physical smoke job lifecycle.

### FlashForge Connector temperature checkpoint — 2026-10-21

- Đã thêm RPC `printer.temperature.request/result` vào `connector_protocol`, có model theo heater (`nozzle`, `bed`, `chamber`), model Creator 5 và extruder index; result chỉ trả target/observed đã sanitize.
- Connector FlashForge đọc `/detail`, kiểm tra state `IDLE/RUNNING/PAUSE/FINISH`, gửi đúng một `temperatureCtl_cmd`, rồi poll `/detail` bounded để đọc lại. Timeout/readback failure không gửi lại command.
- AD5M dùng `rightNozzle` và `platform`; Creator 5 dùng mảng `nozzles` bốn phần tử với sentinel `-200`; chamber chỉ Creator 5 Pro, tối đa 65°C. Creator 5 không bị coi là TCP.
- Backend gateway whitelist, transport và ba route nhiệt độ đã nối Connector; route giải mã check code chỉ trong request memory và không gọi `PrinterManager` khi `connection_mode=connector`.
- Verification: temperature fake HTTP + agent + transport `19 passed`; Connector printer integration selection `5 passed`; compileall, Ruff và `git diff --check` đạt. Pydantic protected-namespace warnings hiện hữu.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; chưa có firmware capture, emulator hoặc máy FlashForge thật. Chưa thêm material/tool-map hay camera relay.
- Đã bổ sung integration route: Creator 5 Pro nozzle qua RPC với extruder index, Creator 5 thường chamber bị từ chối trước RPC, không gọi `PrinterManager` và không trả credential. Gateway result validation đã whitelist `printer.temperature.result`.
- Bước tiếp theo: bounded polling cho job control và physical smoke nếu có máy; giữ `source_inferred`/`hardware_verified=false`.

### FlashForge Connector job-control polling checkpoint — 2026-10-21

- Job control qua Connector hiện poll `/detail` tối đa 5 lần, cách nhau 350 ms sau một lần gửi `/printGcode` hoặc `jobCtl_cmd`; không retry side-effect.
- Start chỉ xác nhận thành công khi state là `RUNNING` và filename readback khớp file yêu cầu; pause/resume/cancel xác nhận state đích như trước.
- Verification: control + agent + transport unit `17 passed`; direct provider job-control regression `8 passed`; Connector pause route integration `1 passed`; compileall, Ruff và `git diff --check` đạt. Warnings Pydantic hiện hữu.
- Giao thức vẫn `source_inferred`, `hardware_verified=false`; physical smoke còn thiếu. Bước kế tiếp: physical smoke hoặc chuyển sang rà một capability Connector chưa hỗ trợ, không đổi trạng thái xác minh phần cứng.

### FlashForge Connector capability snapshot checkpoint — 2026-10-21

- Sửa capability snapshot để Connector không còn báo tất cả thao tác `unavailable` dù đã có RPC.
- Connector báo status, upload/start/job control, nozzle/bed temperature và bed-leveling-before-print là `implemented`; file listing `partial`. Creator 5 có multi-tool temperature; chamber chỉ Creator 5 Pro.
- Camera, fan, filtration, material configuration, delete/navigation/storage và tool/platform mapping vẫn unavailable trên Connector.
- Verification: FlashForge contract unit `13 passed`, capability API integration `1 passed`, compileall và Ruff đạt. Capability implemented phản ánh code path, không phải xác nhận phần cứng; `source_inferred`, `hardware_verified=false`.
- Bước tiếp theo: physical smoke khi có phần cứng; nếu chưa có, rà soát safety/timeout và RPC coverage.

### FlashForge Connector operation deadline checkpoint — 2026-10-21

- Thêm deadline tổng `timeout_ms` bao quanh pre-read, command và readback cho job control và temperature; không để mỗi lần poll cộng dồn vượt RPC budget của gateway.
- Timeout sau command chỉ trả lỗi đã sanitize; helper không retry side-effect. Test cố ý treo readback sau command xác nhận chỉ có một `/control`.
- Verification: Connector control/temperature/agent/transport + contract unit `36 passed`; Connector pause/temperature/capability integration filter `4 passed`; Ruff và compileall đạt.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; lỗi timeout sau khi command được gửi vẫn có nghĩa trạng thái thật có thể chưa rõ, cần status readback độc lập sau đó.
- Bước tiếp theo: physical smoke nếu có máy; nếu chưa, review Connector response correlation, cancellation và behavior sau timeout trên toàn bộ FlashForge RPC.

### FlashForge Connector response correlation, cancellation and upload staging checkpoint — 2026-10-21

- Gateway hiện gắn pending response với connector/session/request ID/response type, từ chối request ID đang chờ bị trùng, áp deadline xuyên suốt send lock + WebSocket send + response wait, và dọn pending entry trên mọi đường thoát.
- Disconnect/replacement giải phóng các request của session cũ. Response trễ/không biết, sai session, sai response type và trùng được đếm riêng; metrics API xuất các counter này.
- Với control/start, temperature và upload, timeout/send failure/disconnect sau khi bắt đầu gửi được phân biệt thành `delivery_unknown`; HTTP trả 504 với request ID và `detail.outcome`, metric `request_delivery_unknown_total` được xuất. Timeout trước khi lấy send lock không bị coi là đã phát lệnh.
- Control/start và nhiệt độ chạy thêm status RPC read-only sau `delivery_unknown`, đính kèm state/filename/progress/temperatures nếu Connector trả lời. Response vẫn là 504 `delivery_unknown`, không coi snapshot nhất thời là xác nhận thành công/thất bại. Upload không suy luận kết quả từ recent-file listing thiếu metadata integrity.
- UI stop/pause/resume và temperature panel nhận diện lỗi có `detail.outcome=delivery_unknown`, hiển thị cảnh báo được dịch đủ 10 locale và buộc refresh printer status; không tự gửi lại command.
- Không tự retry và chưa tuyên bố idempotency; client cần tiếp tục đối chiếu status mới trước khi thao tác lại để tránh lặp side-effect.
- Upload transport dùng request ID riêng cho `begin/chunk/finish`; phase lỗi, timeout hoặc caller bị hủy sẽ gửi best-effort `abort` riêng (shielded, deadline tối đa 3 giây). Connector tự dọn idle staging session sau 15 phút, cleanup mỗi 30 giây; giới hạn 4 session và 512 MiB declared staging mỗi Connector. Disconnect cũng đóng mọi session; duplicate `begin` không xóa session cũ.
- Verification: Connector gateway/agent/transport + FlashForge control/files/temperature/upload unit `50 passed`; metrics, temperature reconciliation và file-start reconciliation integration `40 passed`; Ruff, compileall, `git diff --check`, i18n parity và frontend production build đạt. Build hoàn tất với cảnh báo Node `20.12.2` thấp hơn Vite yêu cầu `20.19+` và bundle lớn; Pydantic protected-namespace warnings hiện hữu, Git cảnh báo LF sang CRLF.
- Hạn chế quan trọng: backend timeout/cancellation không dừng operation đang chạy trong Connector; side-effect có thể hoàn tất, caller không tự retry và cần status readback riêng. `abort` chỉ xóa staging bytes, không hủy HTTP upload đã bắt đầu tới printer; abort best-effort có thể thất bại khi Connector offline, khi đó TTL/disconnect là fallback.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; chưa có packet capture firmware, emulator hay máy thật. Phase 12 tiếp tục `DOING`, không coi code path là hardware verified.
- Bước tiếp theo: nếu UI cần tự làm mới, thêm endpoint truy vấn theo request ID; định nghĩa xử lý khi snapshot chưa kết luận được, reconciliation upload từ metadata đầy đủ, rồi physical smoke khi có máy.

### FlashForge Creator 5 tool-map checkpoint — 2026-10-21

- Đã kiểm tra trực tiếp upstream `creator5-api.js` và `flashforge-creator5-adapter.test.js` tại commit `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`.
- `materialMappings` có item `{toolId, slotId, materialName, toolMaterialColor, slotMaterialColor}`; `toolId` zero-based logical tool, `slotId` one-based vật liệu Creator 5. Test upstream xác nhận đổi `toolMap` `{0: 2, 1: 0}` thành slot lần lượt 3 và 1.
- Upstream yêu cầu caller truyền `toolMap`, `usedLogicalTools`, `logicalTools`, rồi dùng `/detail` để lấy physical slot metadata. Không tự suy ra mapping từ filament slot metadata.
- Printbuddy hiện chỉ có `slot_id` từ slicer cho filament/material requirement; helper Creator 5 chỉ dùng số slot để đặt `gcodeToolCnt`. Hàm nozzle mapping hiện có dành cho Bambu dual-nozzle. Queue `ams_mapping` mang semantics Bambu và bị chặn cho Creator 5.
- Quyết định: mapping Creator 5 vẫn unavailable; không cast `slot_id` thành `toolId`, không gửi `materialMappings`, không đổi Connector payload. File local chỉ dùng cấu hình mapping đã lưu trên máy.
- Bước tiếp: thiết kế model/queue field riêng cho Creator 5 logical-tool→physical-slot map, xác định parser slicer metadata tạo logical tool IDs, direct-start serialization/validation và tests queue round-trip; chỉ sau đó mới cân nhắc Connector RPC.
- Chưa có thay đổi runtime code trong checkpoint; không cần test run. Upstream source/test không thay cho firmware capture hoặc máy thật; evidence `source_inferred`, `hardware_verified=false`.

### FlashForge Creator 5 explicit queue mapping — 2026-10-22

- Đã thêm `creator5_material_mappings` riêng vào PrintQueueItem, Pydantic create/update/response, DB migration và frontend API types; payload entries giữ upstream names `toolId`, `slotId`, `materialName`, `toolMaterialColor`, `slotMaterialColor`.
- Queue API chỉ nhận map cho máy Creator 5 được chỉ định; không được ghép với `ams_mapping`. Scheduler validate JSON/shape/ranges/duplicate logical IDs trước upload, sau đó `PrinterManager` chuyển mapping vào `POST /printGcode`. Provider giữ status + recent-file precheck/readback.
- File-local start vẫn từ chối mapping; không tự suy luận `toolId` từ slicer `slot_id`. Connector không có RPC map nên chưa hỗ trợ. Chưa có UI; caller hiện phải cung cấp map explicit cho queue job.
- Verification: selected tests `47 passed` với `--noconftest`; Ruff, compileall, TypeScript `tsc --noEmit`, `git diff --check` đạt. Pytest thường không nạp fixture được do package môi trường thiếu `TLS_FTPHandler` trong `pyftpdlib.handlers`.
- Parser logical tool và scheduler completeness gate hiện đã được thêm; chi tiết mới nhất ở checkpoint 2026-10-22 bên dưới. Vẫn cần fixture slicer thật, UI mapping và queue persistence integration tests. Giữ Connector mapping unavailable.

### Creator 5 logical-tool parser checkpoint — 2026-10-22

- Parser G-code/3MF mới đọc `T<n>` ngoài comment, filament usage metadata, và chọn plate theo `plate_id` 1-based. Giới hạn G-code nhúng 16 MiB, G-code rời 64 MiB, ZIP 10.000 entry.
- Khi queue có `creator5_material_mappings`, scheduler yêu cầu tập `toolId` khớp chính xác logical tools được parser xác định trước upload; metadata thiếu/mơ hồ, tool ngoài 0-3, file/plate lỗi đều fail closed. Không suy luận từ `slot_id`.
- Tool IDs là hợp của lệnh `T<n>` và filament usage metadata; metadata palette chỉ dùng làm fallback một tool khi không có bằng chứng khác.
- Verification: parser + queue mapping schema + Creator 5 provider selected tests `51 passed`; Ruff, compileall và `git diff --check` đạt. Pydantic warning `model_pictures` hiện hữu.
- Fixtures là tổng hợp; chưa thử 3MF từ slicer Creator 5/Orca/FlashPrint, firmware hoặc máy thật. `source_inferred`, `hardware_verified=false`; UI và Connector mapping còn thiếu.
- Bước tiếp: kiểm tra parser với 3MF thực, sau đó UI queue mapping và persistence integration tests. Giữ mapping Connector unavailable tới khi có RPC riêng.

## GitHub và đồng bộ mã nguồn

- Repository riêng tư lưu mã nguồn tùy chỉnh: [quocanhcgd/DMBuddy](https://github.com/quocanhcgd/DMBuddy).
- Local repository dùng nhánh `main`, remote `origin` qua HTTPS và đã push commit khởi tạo.
- Quy trình cập nhật: kiểm tra thay đổi và secret → chạy test phù hợp → `git add`/`git commit` → `git push origin main`.
- Không đưa dữ liệu runtime hoặc thông tin nhạy cảm lên GitHub: `data/`, `archive/`, `logs/`, `*.db`, `.env`, credential/token/key runtime đã được loại bởi `.gitignore`.
- Repository upstream gốc vẫn được tham chiếu trong tài liệu; không đổi các định danh kỹ thuật của ứng dụng chỉ vì repository tùy chỉnh này.
- Hướng dẫn cài trên máy chủ Linux mới nằm ở [`docs/deploy-new-server.md`](docs/deploy-new-server.md); script cập nhật GitHub/Docker Compose an toàn là [`scripts/update-server.sh`](scripts/update-server.sh), yêu cầu working tree sạch, fast-forward và backup `/app/data` trước khi restart.

### Creality printer artwork checkpoint — 2026-10-22

- Existing Creality K3 record keeps its model `Creality K3`; image changes come from frontend model-to-image mapping and require no printer re-add.
- `Creality K3` and alias `K3` now resolve to cache-busted `/img/printers/creality-k3-v2.png`. Asset is present in both `frontend/public/img/printers/` and `static/img/printers/`.
- Current UI lists the existing K3 printer, and both Vite `:5174` and app server `:8000` return HTTP 200 for the new image.
- Verification: printer image/model tests `20 passed`; `npx tsc --noEmit` passed. Full frontend run surfaced unrelated pre-existing locale assertion failures in `SystemHealthPanel` and was stopped.
- Detailed evidence and reload guidance: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “Printer artwork refresh checkpoint”.

### K3 firmware configuration checkpoint — 2026-10-22

- User supplied K3 `printer.cfg`, `factory_printer.cfg`, `sensorless.cfg`, `gcode_macro.cfg`, `printer_params.cfg`, `box.cfg`, `motor_control.cfg`, and Moonraker config. The pasted `sensorless.cfg` matches the Downloads copy; no credentials/tokens found. All includes referenced by `printer.cfg` are present. `motor_control.cfg` is not included and says 350 mm while the active profile says 260 mm.
- Read-only Moonraker query at `192.168.0.158:7125` confirms four extruders, `nozzle_manager` with four nozzle records/heaters, and attached station `CFS-Nano` with T1A-D through T4A-D mapping. Idle sample reports `nozzle_manager.selected=-1`; preserve unknown selection.
- `sensorless.cfg` overrides `G28`; homing may load default nozzle, move to the box extrude/clean position and run pressure checks. Home requires K3-specific safety review and readback; do not assume generic G28 or retry an ambiguous operation.
- Firmware help exposes K3-specific start/pause/resume/cancel, nozzle and BOX macros, but no direct `T0`-`T3`/`NOZZLE_LOAD`/`NOZZLE_REPLACE` commands in the help response. No side-effecting G-code was sent. Do not automate nozzle/material macros before safe before/after readback is proven.
- Next: inspect actual slicer G-code and capture read-only nozzle state after a user-operated change. K3-specific four-heater/nozzle telemetry is implemented, while CFS-Nano normalization and actions remain gated pending evidence. Full detail: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “K3 configuration and live Moonraker evidence”.

### K3 read-only nozzle telemetry checkpoint — 2026-10-22

- Moonraker provider now queries K3-only `nozzle_manager` plus advertised four extruder objects and returns four heater temperatures, diameters and sanitized `raw_data.creality_k3` state. Other Moonraker models retain existing behavior.
- Unknown `selected=-1` stays unknown; K3 `box` remains raw telemetry and does not pass through the K2 CFS AMS normalizer or enable K2 material actions.
- No nozzle/material commands or UI controls were added. Tests: Moonraker provider `28 passed`, Ruff, compileall and diff check passed.
- Next: compare read-only snapshots around a user nozzle change and inspect real slicer G-code before any K3 nozzle or CFS-Nano action support. Details in [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “Read-only K3 nozzle telemetry checkpoint”.

### K3 active Fluidd/config checkpoint — 2026-10-22

- Fluidd is served at `192.168.0.158:4408` (`v1.30.0-f3e4ac3`); port 80 is 404. Fluidd UI reports no Moonraker connection to `:7125`, but direct read-only Moonraker GET calls work.
- `printer.cfg`, `sensorless.cfg`, `gcode_macro.cfg`, `printer_params.cfg`, `box.cfg`, `factory_printer.cfg`, and `motor_control.cfg` SHA-256 match user-provided files. `motor_control.cfg` is present on printer but excluded by active config.
- Idle runtime conflicts: `nozzle_manager.selected=-1`, `toolhead.extruder=extruder`, macro `CHANGE_T_PARAM.current_num=0`. Preserve active nozzle as unknown. CFS-Nano reports online/connected, but only T1A has populated PLA metadata in this sample.
- No G-code/macro/config write was issued. Nozzle and CFS actions remain gated; next evidence is before/after read-only state around a user-operated change plus real slicer G-code. Details: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “Read-only Fluidd and active-config checkpoint”.

### K3 Fluidd and slicer G-code checkpoint — 2026-10-22

- Fluidd now connects after a fresh load; dashboard READY and Configuration file list are visible. CORS preflight from `http://192.168.0.158:4408` and a read-only Moonraker WebSocket handshake succeed. No config changes were needed; initial UI disconnect was transient.
- Existing Creality Print 7.2 4-color Benchy G-code contains `START_PRINT EXTRUDER_TEMP=220 BED_TEMP=55`, `T0`-`T3` with per-tool `M104 ... Tn` preheat, and `END_PRINT`; no explicit nozzle/CFS macros in inspected tool-change lines. File was read only, not started.
- Standby baseline has no active file; `nozzle_manager.selected=-1`, `toolhead.extruder=extruder`, `CHANGE_T_PARAM.current_num=0`. Last completed print was single-color, so it does not verify `T1`-`T3` behavior.
- This supports investigating `T<n>` as slicer syntax only. Runtime active-nozzle fields still conflict, so capture before/after state around a user-operated nozzle selection; keep nozzle/CFS controls gated. Details: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “Fluidd connection and slicer G-code checkpoint”.

### K3 heater test checkpoint — 2026-10-22

- After user heater test, Moonraker's 600-sample read-only temperature history recorded `extruder1` and `extruder2` targets at `40 C`, with measured peaks about `49.3 C` and `46.5 C`; both are now target `0 C` and cooling. Primary and extruder3 histories showed no nonzero target.
- Nozzle state stayed unresolved (`selected=-1`, `toolhead.extruder=extruder`, macro `current_num=0`), printer standby/no active file. This confirms heating/telemetry only, not tool selection. Peak above target is recorded for review; no Printbuddy heating command was sent. Details: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “User-operated heater test checkpoint”.

### K3 nozzle selection checkpoint — 2026-10-22

- User-operated selection changed the K3 from baseline `nozzle_manager.selected=-1`, all `loaded=0`, to stable `selected=2` with only nozzle ID 2 `loaded=1` in two read-only snapshots. `nozzle_manager.current_extruder` temperature matched `extruder2`; printer stayed standby, heaters off.
- `toolhead.extruder=extruder` and `CHANGE_T_PARAM.current_num=0` remain divergent. Treat K3 `nozzle_manager.selected` as the source for selected-nozzle telemetry; retain other values as separate diagnostics. Existing provider already maps this field to `active_extruder`.
- Hardware-verified selected-nozzle readback for one manual selection only. G-code `T<n>`, start print, nozzle load/unload/replacement, and CFS actions remain unverified/gated. Details: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “User-operated nozzle selection checkpoint”.

### K3 printer-card display checkpoint — 2026-10-22

- The K3 card excludes generic AMS/VT tray data and cached tray values, and hides the generic loaded-spool inventory picker because nozzle-to-spool mapping is not established. The verified E2 Active indication remains visible.
- CFS-Nano stays read-only and separate from AMS/VT; no material action or nozzle-slot inference is enabled. Its status contract and card are now implemented, with unknown material fields left null and rendered as “Unknown”.
- REST and WebSocket carry the typed K3-only status. Provider, WebSocket serialization, and schema suites passed `183` tests under `--noconftest`; Ruff, compileall, TypeScript/build, and diff check passed. Vitest cannot collect due to the installed CommonJS/ESM router conflict; normal pytest startup also hits an incompatible `pyftpdlib` conftest import. Details: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “Read-only CFS-Nano payload and card”.
- The card now shows four slots for the one detected T1 CFS-Nano and nests the module inside the existing Filaments/AMS section grid, using the shared slot-circle visual. It no longer occupies its own section after temperatures. TypeScript/build/diff checks pass; the focused UI test remains uncollectable due to the router ESM conflict. Next: reload the app to visually confirm placement; keep material controls and nozzle-to-slot inference disabled. Details: [`docs/creality-k3-integration-plan.md`](docs/creality-k3-integration-plan.md), “CFS-Nano card layout alignment”.

