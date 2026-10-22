# Kế hoạch triển khai hỗ trợ máy in FlashForge cho Printbuddy

## Mục đích và cách sử dụng

Tài liệu này là kế hoạch triển khai theo từng phase, đồng thời là nhật ký tiến trình để các phiên AI/kỹ sư sau có thể tiếp tục mà không bỏ qua các hợp đồng hiện có của Printbuddy.

- Phạm vi chính: FlashForge Adventurer 5M/5M Pro (AD5M) và Creator 5/Creator 5 Pro.
- Phạm vi kết nối: direct LAN/VPN trước, Connector sau.
- Nguồn giao thức tham khảo: docs/flashforge-integration-reference.md, dựa trên Andy-Knight/Print-Farm-Controller commit 7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5 (v0.59.0).
- Không xem mã nguồn tham khảo là API chính thức. Mọi command/payload phải được ghi là inferred, emulator-tested, hoặc physical-tested.
- Không sửa/ghi đè thay đổi chưa commit của người dùng. Trước mỗi phase phải kiểm tra git status --short.

## Quy ước tiến trình

- TODO: chưa bắt đầu.
- DOING: đang thực hiện; chưa được coi là hoàn thành.
- BLOCKED: không thể tiếp tục an toàn vì thiếu firmware capture, máy thật, quyết định sản phẩm hoặc contract phụ thuộc. Phải ghi rõ blocker.
- DONE: đầu ra đã có và test/criteria của phase đã đạt.
- DEFERRED: có chủ ý đưa ra sau MVP; phải ghi lý do và ảnh hưởng.

Mỗi lần tiếp tục công việc, AI phải:

1. Đọc file này, MEMORY.md, docs/printbuddy-system-memory.md và docs/flashforge-integration-reference.md.
2. Đọc lại diff hiện tại và chạy kiểm tra phù hợp với phase đang DOING.
3. Cập nhật bảng trạng thái và nhật ký ở cuối file sau khi có kết quả thực tế.
4. Không đánh dấu DONE chỉ vì code đã viết; phải có test và tiêu chí nghiệm thu tương ứng.

## Trạng thái hiện tại

Ngày ghi kế hoạch: 2026-10-20 (Asia/Saigon).

| Phase | Trạng thái | Phụ thuộc | Kết quả hiện tại |
| --- | --- | --- | --- |
| 0. Baseline và bảo toàn working tree | DONE | - | Đã đọc kiến trúc/provider/Connector; working tree có thay đổi chưa commit, cần giữ nguyên. |
| 1. Chốt contract và capability | DONE | 0 | Đã thêm `flashforge_contract.py` và test model/port/capability/validation; pytest suite chung đang bị dependency `pyftpdlib` chặn trước khi chạy test. |
| 2. Model/schema/secret/migration | DONE | 1 | CRUD integration xác nhận create/update/read; check code được Fernet hóa, response public scrub credential, migration SQLite idempotent và không đổi token provider khác. Chưa có PostgreSQL test path trong môi trường này. |
| 3. Low-level HTTP/TCP/protocol library | DONE | 1 | HTTP JSON/multipart và AD5M TCP sync/async lock/listing/M661 parser đã có fake-response + localhost wire tests. Discovery chuyển sang Phase 11; upload Expect fallback chuyển sang Phase 8. Không có firmware evidence. |
| 4. Provider AD5M direct | DOING | 2, 3 | Verify/status, TCP file list + HTTP recent fallback, upload/start/pause/resume/cancel, nozzle/bed temperature, cooling/chamber fan, camera proxy và listing completeness đã có fake/API tests. Filtration và standalone calibration còn planned; hardware smoke chưa chạy. |
| 5. Provider Creator 5 direct | DOING | 2, 3 | Status bốn nozzle/recent-file, thermal/material control, multipart upload với số tool rõ ràng, start recent-file, job control, direct camera proxy và queue-owned material mapping có precheck/reconcile. Parser logical tool đã nối với G-code/3MF plate; UI và hardware smoke còn lại. |
| 6. PrinterManager và lifecycle/status | TODO | 4, 5 | Manager chỉ tạo provider hiện có. |
| 7. CRUD, verify, diagnostics, capabilities | DOING | 2, 4, 5, 6 | Connector verify FlashForge `/detail` đã có; direct route/diagnostics và hardware verification còn lại. |
| 8. File browser/upload/start/queue | TODO | 4, 5, 6, 7 | Nhiều route còn gọi Bambu FTP trực tiếp; cần tách provider. |
| 9. Controls, thermal, print safety | TODO | 4, 5, 6, 7 | Chưa có capability gate FlashForge. |
| 10. Camera | DOING | 4, 5, 7 | AD5M và Creator 5 direct đã dùng effective source, activation, snapshot/live proxy và fan-out; Connector relay, physical smoke và firmware close semantics còn thiếu. |
| 11. Discovery direct LAN | DOING | 3, 7 | Đã chốt parser thuần cho packet legacy 140-byte, modern 276-byte và TCP `~M115`; network wiring còn phải giới hạn LAN và không tự lưu printer. |
| 12. Connector discovery/verify/control/status/files | DOING | 3, 7-11 | Discovery/verify/status/files/upload/start/job control/temperature FlashForge đã nối; capability snapshot vẫn cần theo dõi. Camera relay, fan/material controls, physical smoke và network evidence còn thiếu. |
| 13. Frontend | TODO | 7-12 | Add Printer/UI capability chưa có FlashForge. |
| 14. Emulator và contract tests | TODO | 3-12 | Cần fake server ổn định trước khi test route/queue. |
| 15. Physical pilot và phát hành | TODO | 1-14 | Chưa có bằng chứng firmware phần cứng. |

## Nguyên tắc kiến trúc bắt buộc

1. FlashForge là provider riêng, không biến Bambu client thành client đa hãng bằng các nhánh if rải rác.
2. Tách flashforge_ad5m và flashforge_creator5 ở capability/model policy. Creator 5 không được nhận capability TCP 8899 chỉ vì discovery quảng bá command port.
3. Domain service gọi provider contract; không mở socket trực tiếp từ route, scheduler hoặc frontend.
4. Capability phải là dữ liệu backend authoritative. UI chỉ hiển thị/cho phép thao tác đã được capability cho phép.
5. Mọi thao tác có side effect phải có timeout, error mapping, reconcile sau timeout và không retry mù quáng.
6. Secret checkCode/serial credential không được log, trả trong response public, telemetry, diagnostics hoặc Connector result.
7. Direct và Connector dùng cùng domain operation contract; Connector chỉ thay transport, không thay đổi policy/permission/safety.
8. Tạm thời chỉ hỗ trợ một app instance như Connector plan hiện quy định; không thiết kế queue memory-only khiến sau này không thể mở rộng.

## Phase 0 — Baseline, inventory và bảo toàn thay đổi hiện tại (DONE)

### Đã làm

- Đọc provider boundary: backend/app/services/printer_providers/factory.py, base.py.
- Đọc model/schema: backend/app/models/printer.py, backend/app/schemas/printer.py.
- Đọc lifecycle: backend/app/services/printer_manager.py.
- Đọc route/file/queue/camera/Connector và các kế hoạch Connector hiện có.
- Đọc giao thức FlashForge và ghi vào docs/flashforge-integration-reference.md.

### Việc phải kiểm tra lại trước phase tiếp theo

- Chạy git status --short và lưu ý các file đang sửa bởi người dùng.
- Tìm tất cả call site network/secret bằng rg:

  rg -n "ip_address|access_code|provider|create_printer_client|list_files|upload_file|start_print|camera" backend connector connector_protocol frontend

- Lập danh sách call site trong plan này, không coi một lệnh rg duy nhất là bằng chứng đã bao phủ hết.

### Tiêu chí hoàn thành

- Không mất hoặc revert thay đổi chưa commit.
- Danh sách module ảnh hưởng được cập nhật trước khi thêm provider.

## Phase 1 — Chốt contract FlashForge và capability (DONE)

### Mục tiêu

Chốt tên provider, model identity, dữ liệu cấu hình, capability và trạng thái chuẩn hóa trước khi viết client mạng.

### Quyết định cần ghi thành code/test

- Provider IDs: flashforge_ad5m, flashforge_creator5.
- Model allowlist: Adventurer 5M, Adventurer 5M Pro, Creator 5, Creator 5 Pro.
- Config tối thiểu: ip/host; HTTP port mặc định 8898; AD5M TCP port mặc định 8899; camera port mặc định 8080; serial number; check code; provider_options có schema.
- Creator 5 không có TCP port capability.
- State chuẩn: connected, normalized printer state, progress 0-100, filename, layer/time nếu có, nozzle(s), bed, chamber nếu có, camera availability, firmware/model, provider errors.
- Capability matrix phân biệt supported, read_only, unavailable, unknown cho status, files, upload, delete, print, pause/resume/cancel, temperatures, fans, filtration, bed leveling, chamber, materials, camera.
- Unknown data phải là None/unknown; không chuyển thiếu filament presence/nozzle diameter thành giá trị giả.

### File dự kiến

- backend/app/schemas/printer.py
- backend/app/services/printer_providers/base.py
- Module capability dùng chung nếu boundary hiện tại chưa đủ.
- Test schema/capability trong backend/tests/unit/.

### Test và nghiệm thu

- Schema chấp nhận provider/model/ports hợp lệ, từ chối port ngoài 1..65535, host không hợp lệ, model không phù hợp provider.
- Creator 5 không có field/capability TCP trong config runtime.
- Legacy printer không khai báo provider vẫn giữ default hiện tại là bambu.
- Capability serialize ổn định và không chứa secret.

### Điểm dừng

Nếu chưa thống nhất tên provider hoặc trạng thái unknown/unsupported, dừng trước Phase 2; không bắt đầu client bằng contract mơ hồ.

## Phase 2 — Model, schema, secret và migration (DOING)

### Mục tiêu

Đưa FlashForge vào persistence mà không phá dữ liệu Bambu/provider hiện có.

### Công việc

1. Mở rộng PrinterProvider literal và provider normalization.
2. Xác định mapping credential hiện tại: access_code có đang xuất trong PrinterResponse hay không. Nếu có, sửa secret scrubbing trước khi lưu FlashForge.
3. Mở rộng Printer model nếu cần port riêng/model-specific config. Ưu tiên provider_options có JSON validation khi không cần thêm cột; nếu thêm cột, cập nhật migration idempotent SQLite/PostgreSQL trong backend/app/core/database.py.
4. Cập nhật PrinterCreate, PrinterUpdate, PrinterResponse và validators để enforce provider/model/connection mode/connector binding.
5. Quy định credential cho direct và connector. Connector mode cần encryption-at-rest hoặc envelope đã chốt, không gửi secret về frontend.
6. Bổ sung migration test: DB cũ vẫn khởi động; DB mới tạo printer FlashForge; legacy check code được mã hóa idempotent; failure không xóa dữ liệu.

### Test và nghiệm thu

- Unit schema/provider tests.
- Integration create/update/get printer cho từng provider/model.
- Assert response public không có check code/access credential.
- Assert provider_options invalid JSON/unknown fields/oversize bị từ chối.
- Chạy migration trên SQLite và PostgreSQL test path nếu CI có.

### Điểm dừng

Không nối client vào route nếu secret vẫn lộ qua PrinterResponse, log hoặc error body.

## Phase 3 — Low-level FlashForge protocol library (DONE)

### Mục tiêu

Tách phần giao thức thuần khỏi provider lifecycle để test bằng fake server và tái sử dụng cho direct/Connector agent.

### Module gợi ý

- backend/app/services/flashforge/http.py: HTTP request, auth body, timeout, status/code/error mapping, response size limit, no redirect.
- backend/app/services/flashforge/tcp.py: connect, M601/M661/M602, chunk/settle handling, cancellation, lock per printer.
- backend/app/services/flashforge/http.py: multipart streaming `/uploadGcode`, filename/path guard, content length.
- backend/app/services/flashforge/normalize.py: file-list normalization; status/discovery normalization remains pending until payload samples are verified.
- Discovery packet parse, UDP send/receive và bounded M115 probe thuộc Phase 11 để cùng kiểm soát giới hạn subnet/concurrency.
- Chỉ đặt code trong connector/ khi đó là code dùng độc lập; không import backend.app vào Connector phát hành.

### Chi tiết HTTP phải triển khai

- Base URL chỉ từ validated host/port.
- POST JSON serialNumber + checkCode.
- HTTP non-2xx, JSON malformed, code != 0, timeout, reset và oversized response thành error types chuẩn.
- LAN mode error/code -2 thành lỗi actionable nhưng không lộ credential.
- Serialize request cùng printer để tránh firmware bị quá tải.

### Chi tiết TCP phải triển khai

- Lock theo printer và tcp_port.
- Acquire ~M601 S1, reject Control Failed/busy.
- M661 chấp nhận ACK + payload nhiều chunk, settle timeout có giới hạn.
- Parser path /data/, 0:/user/, legacy line form; chỉ extension cho phép; chống duplicate.
- Release ~M602 trong finally, close socket cả khi task bị cancel.

### Test và nghiệm thu

- Fake HTTP transports và loopback TCP server trong `backend/tests/unit/test_flashforge_protocol.py`.
- Test timeout, cancellation, malformed payload, code âm/dương, LAN disabled, duplicate file, unicode filename, concurrent M601.
- Không có test nào dùng network Internet thật.
- ruff check không báo lỗi; test async không block event loop.

### Tiến độ hiện tại

- Đã thêm `backend/app/services/flashforge/errors.py`, `http.py`, `tcp.py`, `normalize.py` và package exports.
- HTTP client POST body có serial/check code, `code == 0`, HTTP 2xx, no-redirect, timeout, response-size bound và error sanitization; có helper `/detail`, `/gcodeList`, `/control`, `/printGcode` và streaming multipart `/uploadGcode` với `printNow=false`.
- TCP client chỉ cho AD5M contract, dùng lock theo host/port, TCP_NODELAY, acquire → M661 → release ở `finally`, giới hạn response và timeout; có sync worker-thread path và async-native path.
- M601 chỉ được coi là thành công khi firmware trả `Control Success` hoặc ACK `ok`; busy/failure và phản hồi không rõ đều bị từ chối.
- M661 parser đã xử lý delimiter `/data/`, legacy `info_list.size`, prefix `0:/user/`, extension allowlist, Unicode và duplicate.
- Fernet integration tests đạt 3/3: check-code roundtrip, plaintext fallback bị từ chối, migration chỉ mã hóa record FlashForge.
- `backend/tests/unit/test_flashforge_protocol.py`: 30 tests; gộp schema/contract/protocol đạt 57 tests bằng `pytest --noconftest` (chỉ HTTP/TCP loopback, không dùng Internet).
- Async TCP cancellation đã kiểm chứng trên loopback server; server nhận đủ M601 → M661 → M602 trước khi socket đóng.
- Client AD5M đã được tích hợp vào factory/PrinterManager test connection trong Phase 4; status callback và file-list fallback đã có. Chưa có firmware/hardware evidence. Discovery UDP/M115 thuộc Phase 11; upload `Expect: 100-continue` fallback thuộc Phase 8.

### Điểm dừng

Nếu chưa mô phỏng được M661 nhiều chunk và release lock khi cancellation, chưa được dùng TCP trong provider.

## Phase 4 — Provider AD5M direct (DOING)

### Mục tiêu

Đưa Adventurer 5M/5M Pro vào factory và chạy được verify/status/file/job cơ bản qua direct LAN.

### Công việc

- Tạo backend/app/services/printer_providers/flashforge_ad5m.py theo PrinterClientProtocol.
- Implement connect/disconnect/check_staleness bằng HTTP /detail và status polling bounded.
- Map status/progress/temp/filename/firmware vào state Printbuddy; giữ trường không có là unknown.
- Implement list_files: M661 full list + /gcodeList recency overlay; fallback recent-only có warning.
- Implement upload streaming, verify file, start print với levelingBeforePrint, pause/resume/cancel, request status.
- Nozzle/bed target dùng `temperatureCtl_cmd` với field `rightNozzle`/`platform`, giới hạn theo model contract; yêu cầu state đọc được và reconcile target qua `/detail` sau lệnh.
- AD5M file storage hiện được coi là phẳng: list/upload/start chỉ nhận root; thư mục con, storage selector, AMS mapping và platform selection bị từ chối rõ ràng vì protocol chưa chứng minh hỗ trợ.
- Sau upload, route đối chiếu file với listing theo path; start chỉ xác nhận thành công khi status báo đang in đúng filename. Timeout của lệnh side-effect được reconcile, không gửi lệnh lại.
- `GET /printers/{id}/capabilities` trả state `implemented`/`partial`/`read_only`/`planned`/`unavailable`, transport, protocol evidence và hardware verification; không nâng protocol reference thành capability đã triển khai. Connector mode hiện báo unavailable.
- `GET /printers/{id}/files` thêm `listing.completeness`, `source` và warning cho fallback recent-only; các provider khác không có metadata này vẫn giữ response hiện có.
- Verify diagnostics phân biệt lỗi auth/LAN mode, timeout và command busy bằng thông báo thao tác được, không echo lỗi chứa credential.
- Nozzle/bed, cooling/chamber fan và direct camera stream/snapshot đã có code path. Camera dùng proxy hiện hữu với stream-token auth, URL sanitization và fan-out; mở camera bằng `streamCtrl_cmd`, lấy URL cùng host/port từ `/detail` hoặc fallback đã validate. Firmware chưa có close command được chứng minh, nên proxy stop chỉ dừng upstream; `hardware_verified=false`. Filtration giữ `planned` vì thiếu state readback. Các thao tác leveling cần được xác nhận trong hardware smoke.
- Delete file chỉ bật sau khi có evidence endpoint/semantics; không tự suy ra từ M661.
- Map provider exceptions sang lỗi domain an toàn.
- Đăng ký provider ở factory và __init__.py nếu cần.

### Test và nghiệm thu

- Factory tạo đúng client và không ảnh hưởng Bambu/Moonraker/Prusa/Elegoo tests.
- Provider tests cover every protocol call/body, normalized state, fallback, busy TCP và side-effect reconciliation.
- Fan tests xác nhận `coolingFan`/`chamberFan` payload, alias/range validation và timeout reconciliation không retry side effect.
- Camera tests xác nhận derived direct source, camera port, URL same-host validation, command timeout reconciliation không retry, snapshot activation và stream fan-out cleanup.
- Route integration kiểm tra upload/start/file-list delegation, từ chối path/storage/options chưa hỗ trợ, conflict và upload reconciliation.
- PrinterManager.test_connection trả diagnostic theo provider/model.
- Direct smoke với emulator/fake server: verify -> connect -> status -> list -> upload -> verify -> start -> pause -> resume -> cancel.

## Phase 5 — Provider Creator 5 direct (DOING)

### Mục tiêu

Hỗ trợ Creator 5/Pro mà không thừa hưởng giả định TCP/single-tool của AD5M.

### Công việc

- Tạo backend/app/services/printer_providers/flashforge_creator5.py.
- /detail normalize bốn tool/nozzle/slot; không coi currentSlot là active tool.
- Creator 5 Pro có chamber sensor/target đến 65 °C; base Creator 5 không invent chamber values. Đã nối route riêng Pro, precheck/readback bounded; Creator 5 thường và Connector bị từ chối.
- temperatureCtl_cmd dùng mảng bốn nozzle với -200 cho phần tử không đổi; range 320/120 °C theo reference nhưng phải gắn firmware/model policy.
- Material config `msConfig_cmd` dùng slot 1-based, allowlist material/color lấy đúng từ reference, chỉ idle, đọc giá trị còn thiếu khi đổi từng trường và xác minh bounded retries.
- /gcodeList là recent-only; expose completeness/warning.
- /uploadGcode và /printGcode tách hai bước; Creator 5 multipart dùng `printNow=false`, `useMatlStation=true`, `gcodeToolCnt` (1-4 do request khai báo, mặc định 1), `flowCalibration=false`, `timeLapseVideo=false`. Upload xác minh file xuất hiện trong HTTP recent list; danh sách này không đầy đủ nên không chứng minh size/content.
- /printGcode chỉ chạy khi idle/finish/failed và file hiện trong HTTP recent list; sau command phải xác nhận `/detail` đang chạy đúng tên file. Job pause/resume/cancel cũng precheck state, gửi một lần rồi reconcile; ACK một mình không xác nhận thành công.
- Multi-tool `materialMappings` vẫn tắt tới khi Printbuddy có metadata sliced-owned/tool-map contract đáng tin. Không lấy `tool_count` làm bằng chứng map hay tự gán PLA/color cho file local.
- Creator 5 direct camera hiện có effective-source, provider activation, validated URL/fallback và proxy flow; protocol vẫn source-inferred và chưa có hardware smoke.
- Không expose TCP 8899 capability dù discovery packet có command port.

### Test và nghiệm thu

- Unit tests cho bốn tool, 1-based slots, active-tool ambiguity, Creator 5 vs Pro chamber, per-tool temperature, material readback và recent-only warning.
- Test model/config không cho phép AD5M-only options.
- Smoke riêng cho Creator 5 và Pro; không dùng cùng fixture với AD5M nếu payload khác.

### Điểm dừng

Nếu firmware thật trả payload khác làm không xác định tool/slot, trả unknown/review và dừng feature mapping; không đoán.

## Phase 6 — PrinterManager, reconnect và lifecycle (TODO)

### Mục tiêu

Provider FlashForge hoạt động trong vòng đời ứng dụng như provider hiện có.

### Công việc

- PrinterManager tạo đúng client theo provider, callbacks print start/running/complete/error và reconnect.
- Xác định polling interval/backoff; không mở một TCP M661 ở mỗi status poll.
- Bounded disconnect khi thay client/provider hoặc shutdown.
- State transition khi offline, LAN mode disabled, busy, paused, error, completed.
- Runtime status có source/provider/model/capability để frontend không suy ra từ field Bambu.
- printer_reconnect.py và diagnostics recognize FlashForge errors.

### Test và nghiệm thu

- Unit lifecycle connect/disconnect/reconnect/offline/recovery.
- Integration route status trả connected/state/error đúng và không rò secret.
- Chạy toàn bộ test PrinterManager hiện có để bảo đảm backward compatibility.

## Phase 7 — CRUD, verify, diagnostics và capability routes (TODO)

### Mục tiêu

Người dùng có thể thêm/sửa/xóa FlashForge qua API với verify rõ ràng trước khi lưu.

### Công việc

- Update backend/app/api/routes/printers.py để provider-specific verify không dùng Bambu MQTT probe.
- Verify AD5M/Creator HTTP auth bằng /detail hoặc endpoint read-only tương đương; TCP connect đơn thuần không phải verify.
- Diagnostics theo từng capability: HTTP, TCP file port, camera, credentials (chỉ pass/fail).
- Tách provider_client operations khỏi Bambu FTP helper trong các route file/control.
- Permission check vẫn ở route; provider chỉ làm protocol.
- Public response chỉ trả safe config; access_code/checkCode backend-side.

### Test và nghiệm thu

- Create/verify success/failure cho direct và connector mode.
- Invalid provider/model/ports/host, wrong credential, LAN disabled, offline và timeout.
- Security tests đảm bảo error/log/response không chứa check code.

## Phase 8 — File browser, upload, print start và queue (TODO)

### Mục tiêu

Tách các thao tác file/print khỏi Bambu-only paths và bảo toàn semantics queue.

### Audit bắt buộc

Tìm và xử lý từng call site trong:

- backend/app/api/routes/printers.py file list/upload/delete/start.
- backend/app/services/background_dispatch.py.
- backend/app/services/print_scheduler.py.
- backend/app/api/routes/print_queue.py.
- backend/app/api/routes/library.py.
- backend/app/main.py callback/lifecycle.

### Quy tắc triển khai

- Provider list_files trả entries chuẩn có complete, source, warning, path/name/size nếu biết.
- Upload dùng Print Library path guard; không nhận arbitrary local path từ request.
- Upload không tự start; start là command riêng với idempotency/reconcile.
- AD5M verify ưu tiên M661 rồi recent fallback; Creator verify chỉ recent list và báo giới hạn.
- Queue preflight không tự mapping material/tool requirement cho printer-local file nếu metadata unknown.
- Job start timeout chuyển sang delivery_unknown/reconcile, không tự retry print.
- Delete file chỉ bật khi protocol evidence có thật; nếu chưa, capability false.

### Test và nghiệm thu

- Upload/verify/start/pause/resume/cancel/delete route tests cho từng provider.
- Queue fixed-printer và next-compatible tests: offline, busy, needs review, file mismatch, restart recovery.
- Background dispatch provider tests chứng minh không gọi bambu_ftp cho FlashForge.
- Path traversal, extension, oversized file, duplicate filename và failed verification.

## Phase 9 — Controls, thermal và print safety (TODO)

### Mục tiêu

Expose đúng command FlashForge với safety policy chung của Printbuddy.

### Công việc

- Capability-gate nozzle/bed/chamber/fan/filtration/leveling/job control.
- Validate numeric ranges, NaN, infinity, negative/over-limit.
- Serialize commands cùng printer; không chạy heating, leveling, start print đồng thời trái policy.
- Re-read status sau command khi firmware ACK không đủ chứng minh state.
- Integrate physical-operation policy/locks tương tự provider hiện tại.
- Không start trong leveling, chamber preheat hoặc fault nếu policy cấm.
- Không implement Creator filtration writable nếu firmware chỉ trả Success nhưng state không đổi.

### Test và nghiệm thu

- Unit command body/range/error mapping.
- Concurrency tests cùng printer và độc lập giữa hai printer.
- Safety audit cho idle/printing/paused/heating/leveling/fault.
- Fault injection: ACK Success nhưng state không đổi phải được báo/reconcile.

## Phase 10 — Camera (DOING)

### Mục tiêu

Đưa camera FlashForge vào camera architecture mà không làm lộ endpoint/credential.

### Quyết định cần chốt

- Direct LAN uses backend proxy/fan-out with the existing stream-token boundary; AD5M and Creator 5 direct paths are connected.
- Connector mode: stream qua Connector session/relay nào; TTL, token, bitrate, max sessions?
- Có cần snapshot fallback cho plate detection không?

### Công việc

- Provider trả camera capability/source, không hard-code FlashForge URL trong frontend.
- AD5M and Creator 5 open/readback/fallback paths are connected; proxy teardown stops the upstream stream. Firmware close remains unavailable because the reference does not define its payload.
- Tích hợp backend/app/services/camera.py, backend/app/api/routes/camera.py, external camera helpers và auth token.
- Không log URL có secret; không dùng camera URL unvalidated để SSRF.
- Connector camera relay remains deferred; direct camera has no physical firmware verification yet.

### Test và nghiệm thu

- Camera unavailable/timeout/malformed MJPEG/close/reconnect.
- Permission and stream token expiry.
- Không ảnh hưởng camera Bambu/Prusa/Elegoo.

## Phase 11 — Discovery direct LAN (TODO)

### Mục tiêu

Discovery FlashForge bounded, không biến thành scan tùy ý hoặc tự động lưu máy.

### Công việc

- Parser fixtures cho legacy 140-byte và modern 276-byte response.
- UDP multicast 225.0.0.9 và broadcast interface trên ports 8899, 19000, 48899.
- Parse PID/model/status/serial/command/event port; deduplicate theo host/identity.
- Bounded configured subnet, concurrency/timeouts.
- AD5M M115 TCP probe chỉ khi cần; Creator không dùng TCP file API.
- Discovery result chỉ endpoint/identity; verify credential riêng trước create.
- Chống broadcast abuse: permission, rate limit, max duration/hosts, cancellation.

### Test và nghiệm thu

- Parser fixtures packet ngắn, null padded, unknown PID, malformed values.
- Network tests mock dgram/socket; không broadcast thật trong unit suite.
- Route tests start/status/stop, permission, bounds, cancellation, dedupe.
- Không trả checkCode hoặc banner raw.

## Phase 12 — Connector protocol và remote operations (DOING; hardware verification pending)

### Mục tiêu

Cho máy FlashForge ở LAN riêng hoạt động qua Connector bằng cùng provider operations, không tạo tunnel TCP tùy ý.

### Thứ tự triển khai

1. Discovery request/result: FlashForge port/service metadata đã có allowlist ở Connector discovery; hardware packet vẫn chưa xác minh.
2. Verify request/result: đã verify HTTP credentials trong memory; result không trả body/secret.
3. Status request/result: đã chuyển FlashForge sang provider status snapshot qua Connector, không dùng TCP reachability làm capability.
4. Command envelope: operation whitelist, printer binding theo request, request ID, timeout/deadline tổng và phân biệt not-delivered với `delivery_unknown` cho side-effect đã có; idempotency key/replay contract còn thiếu.
5. File operations: read-only listing và upload chunked WebSocket (`96 KiB` mỗi chunk, giới hạn staging tổng `512 MiB`/Connector) đã nối. Thiết kế hiện tại truyền bytes trong frame có giới hạn thay cho staging URL; abort RPC và TTL cleanup đã có. Hash/checksum và resume còn thiếu. Không bật retry side-effect.
6. Camera session: chưa nối RPC camera; direct camera của AD5M và Creator 5 là provider path riêng.

### File dự kiến

- connector_protocol/__init__.py hoặc module protocol mới.
- connector/printbuddy_connector.py và provider client package dùng độc lập.
- backend/app/services/printer_transport.py, connector_gateway.py, connector routes và tests.
- Cập nhật docs/printbuddy-connector-task-plan.md nếu task ID hiện có cần nối tiếp.

### Test và nghiệm thu

- Schema rejects unsupported operation/provider/oversized payload/wrong printer binding.
- Connector offline/timeout/duplicate request/late response/reconnect.
- Không có secret trong result, telemetry, logs hoặc browser response.
- Direct mode không fallback âm thầm sang Connector; connector mode không probe direct từ server.
- File transfer cancellation, partial file, checksum mismatch, staging expiry.

### Điểm dừng

Không bật remote print/file production nếu command state chưa phân biệt succeeded, failed và delivery_unknown.

### Checkpoint response correlation, timeout, cancellation và upload staging — 2026-10-21

- Gateway ghép response bằng `(connector_id, request_id)`, session WebSocket hiện hành và response type mong đợi; từ chối request ID trùng đang chờ. Deadline bao gồm thời gian chờ send lock, gửi frame và chờ response.
- Pending request được giải phóng khi response hợp lệ, timeout, cancellation, lỗi send, disconnect hoặc thay session. Response trễ/không biết, sai session, sai loại và trùng có counter riêng trong Prometheus.
- Với `printer.control`, `printer.temperature` và upload, timeout/lỗi/disconnect sau khi bắt đầu gửi hoặc đã gửi nhưng thiếu response ném `ConnectorDeliveryUnknownError`; API control, start, temperature và upload trả HTTP 504 với `detail.outcome=delivery_unknown` cùng request ID. Timeout trước khi lấy được send lock vẫn báo Connector không phản hồi, không gán nhầm là đã phát lệnh. Metric `request_delivery_unknown_total` theo dõi số trường hợp chưa phân giải.
- Control/start và temperature tự gửi một status request read-only riêng sau lỗi delivery-unknown, đính kèm snapshot state/filename/progress/temperatures nếu có. API vẫn giữ `delivery_unknown` và 504 ngay cả khi snapshot trông như trạng thái đích; snapshot có thể đổi sau đó, không phải xác nhận kết quả lệnh. Upload không suy luận thành công từ recent-file listing vì listing thiếu completeness/integrity.
- UI stop/pause/resume và temperature panel nhận diện structured `delivery_unknown`, hiện cảnh báo đã dịch đủ 10 locale và invalidate printer status query ngay; không đề nghị phát lại lệnh.
- Không thêm retry tự động hoặc idempotency claim: cùng một response bị mất vẫn có thể che giấu side-effect đã hoàn tất; client cần đối chiếu snapshot và status mới trước hành động tiếp theo.
- Mỗi phase upload `begin/chunk/finish` dùng request ID riêng. Khi phase lỗi, timeout hoặc caller bị hủy, transport gửi best-effort `abort` riêng (shielded, deadline tối đa 3 giây); Connector dọn session staging khi abort hoặc WebSocket đóng, đồng thời tự hết hạn session idle sau 15 phút với cleanup mỗi 30 giây. Giới hạn 4 session đồng thời và tổng declared staging 512 MiB mỗi Connector; duplicate `begin` không xóa session hiện hành.
- Verification hiện tại: Connector gateway/agent/transport và FlashForge control/files/temperature/upload unit `50 passed`; metrics, temperature reconciliation và file-start reconciliation integration `40 passed`; Ruff, compileall, `git diff --check`, i18n parity và frontend production build đạt. Build cảnh báo Node `20.12.2` thấp hơn Vite yêu cầu `20.19+` và bundle lớn; build vẫn hoàn tất. Pydantic protected-namespace warnings còn hiện hữu.
- Giới hạn: timeout/cancellation ở backend không hủy coroutine hoặc thao tác printer đang chạy trong Connector; side-effect có thể hoàn tất sau khi caller hết hạn và không được tự retry. `abort` chỉ dọn staging bytes, không hủy HTTP upload đã bắt đầu tới printer; abort best-effort có thể thất bại nếu Connector offline, khi đó TTL/disconnect cleanup là fallback. Cần status readback độc lập để phân giải kết quả side-effect không rõ.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; test fake HTTP/WebSocket không xác nhận firmware thật. `git diff --check` chỉ phát cảnh báo Git đổi LF sang CRLF, không phát hiện whitespace error.
- Bước tiếp theo: mở API truy vấn delivery-unknown theo request ID nếu UI cần tự refresh trạng thái, quyết định policy khi snapshot chưa kết luận được và bổ sung upload reconciliation dựa trên nguồn metadata đầy đủ; sau đó physical smoke AD5M/Creator 5/Pro. Chưa đánh dấu Phase 12 hoàn tất.

## Phase 13 — Frontend và UX (TODO)

### Mục tiêu

Cho phép cấu hình và vận hành FlashForge mà không hiển thị capability Bambu không tồn tại.

### Công việc

- Add/Edit Printer: provider/model selector; port fields theo model; serial/check code nhập một lần; verify trước save.
- Hiển thị direct/VPN/Connector route và Connector health.
- Printer detail: status, tools (bốn tool Creator), material slots, temps, file completeness/warning, capabilities.
- File manager: không hiển thị delete/full-list nếu capability false; cảnh báo recent-only Creator.
- Print setup/queue: mapping multi-tool chỉ khi metadata đủ; unknown requirements thành review.
- Controls: disable/guard unsupported features; confirmation cho cancel/heat/level.
- Camera: dùng camera source/session API, không ghép URL từ IP frontend.
- Localization tất cả locale, tối thiểu frontend/src/i18n/locales/vi.ts và en.ts.

### Test và nghiệm thu

- React/Vitest/Testing Library cho provider/model/capability states.
- Mobile/desktop layout, loading/error/offline/Connector states.
- Typecheck/lint/build; không có credential trong rendered DOM, URL hoặc client state.
- Browser smoke với emulator cho add -> status -> file -> print control.

## Phase 14 — Emulator, contract tests và observability (TODO)

### Mục tiêu

Có môi trường lặp lại được trước physical pilot, nhưng không nhầm emulator với firmware proof.

### Công việc

- Thêm FlashForge AD5M HTTP/TCP/camera profile vào virtual printer layer hoặc fake server phù hợp.
- Thêm Creator 5/Pro HTTP/camera profile, bốn tool/slot và fault scenarios.
- Fault injection: LAN mode error, malformed JSON, delayed ACK, busy M601, failed M661, upload accepted but file absent, print ACK nhưng không start, camera unavailable.
- Observability: provider/model/operation latency/error counters, không ghi credential/body.
- Tài liệu endpoint emulator, credentials test-only và cách bật/tắt.

### Test và nghiệm thu

- Contract tests chạy cùng client/provider cho fake và emulator.
- Browser smoke route refresh/SSE/WebSocket không mất state.
- Docker/Windows test không mở port production ngoài ý muốn.

## Phase 15 — Physical pilot, hardening và phát hành (TODO)

### Điều kiện trước pilot

- Có ít nhất một AD5M/AD5M Pro và một Creator 5/Pro hoặc quyết định loại nào không hỗ trợ MVP.
- Ghi model, firmware, network topology, LAN mode, port và ngày test; không ghi credential.
- Có nút dừng vật lý/giám sát người thật; dùng file test nhỏ, nhiệt thấp và bed trống.

### Trình tự test vật lý

1. Discovery không credential.
2. Verify serial/check code, sai credential và LAN disabled.
3. Status idle/printing/paused/error; kiểm tra tiến độ/nhiệt/file name.
4. File list completeness và path normalization.
5. Upload file nhỏ, hash/size/readback.
6. Print start có leveling flag; xác nhận printer thật sự bắt đầu.
7. Pause/resume/cancel và reconcile sau timeout/disconnect.
8. Temperature/fan/filtration/leveling từng thao tác theo capability.
9. Creator material slot/config/readback và bốn tool nếu model hỗ trợ.
10. Camera direct/proxy/Connector và permission.
11. Queue restart/offline/reconnect/bed clearance.
12. Connector mode nếu direct đã đạt tất cả test an toàn.

### Hardening/release

- Chốt firmware support matrix và feature flags.
- Security review SSRF, secret scrubbing, upload path, Connector authorization, camera token, rate limits.
- Chạy backend ruff/pytest; frontend lint/typecheck/test/build; security tests; Docker smoke.
- Cập nhật README, codebase index, system memory, provider roadmap và changelog.
- Phát hành beta/feature flag trước; không bật unattended queue cho capability chưa physical-tested.

## Ma trận đầu ra bắt buộc

Mỗi provider/model chỉ được đánh dấu hỗ trợ một thao tác khi có đủ ba lớp:

| Lớp | Bằng chứng |
| --- | --- |
| Protocol | Unit/contract test xác nhận request parser và error handling |
| Application | Route/manager/queue/Connector test xác nhận policy, permission, reconciliation |
| Hardware | Smoke test trên model + firmware cụ thể, có log kết quả đã khử secret |

Nếu thiếu một lớp, capability phải là unknown/experimental hoặc bị tắt, không quảng cáo là production-ready.

## Lệnh kiểm tra chuẩn

Chạy từ F:\Printbuddy, điều chỉnh theo shell/CI:

- Kiểm tra phạm vi: git status --short
- Tìm call site: rg -n -i "flashforge|ad5m|creator.?5|ip_address|access_code|bambu_ftp|create_printer_client" backend connector connector_protocol frontend
- Backend: ruff check backend; pytest -q backend/tests/unit backend/tests/integration
- Frontend: cd frontend; npm run lint; npx tsc --noEmit; npm test -- --run; npm run build
- Security/container khi phase liên quan hoàn tất: ./test_security.sh; docker compose config

Không chạy toàn bộ suite một cách máy móc sau mọi dòng sửa; chạy test nhỏ nhất cần thiết sau mỗi bước, rồi mở rộng khi boundary/provider/queue thay đổi.

## Nhật ký tiến trình

### 2026-10-20 — Khởi tạo kế hoạch

- Đã đọc repository FlashForge tham chiếu ở commit 7c1687e, lập tài liệu protocol reference.
- Đã đối chiếu Printbuddy provider factory/base, schema/model, PrinterManager, routes file/queue/camera, discovery và Connector.
- Xác định FlashForge chưa được đăng ký trong SUPPORTED_PROVIDERS ở snapshot hiện tại.
- Xác định Connector hiện có discovery/verify/status reachability cơ bản nhưng chưa có FlashForge status/control/file/camera RPC đầy đủ.
- Working tree có nhiều thay đổi chưa commit do người dùng; mọi phase sau phải giữ nguyên và đọc diff trước khi sửa.
- Phase 0 đánh dấu DONE; Phase 1-15 còn TODO.

### 2026-10-20 — Hoàn thành Phase 1

- Đã thêm `backend/app/services/printer_providers/flashforge_contract.py` với provider IDs, model allowlist, port defaults, capability matrix, temperature/tool limits và config validator.
- Đã thêm `backend/tests/unit/services/test_flashforge_contract.py` bao phủ AD5M single-tool/TCP, Creator 5 four-tool/no-TCP, Creator 5 Pro chamber, canonical model/host/port và input invalid.
- `ruff check` cho module/test đạt; smoke import và model/capability assertions đạt.
- `pytest -q backend/tests/unit/services/test_flashforge_contract.py` chưa chạy được vì fixture chung import `TLS_FTPHandler` không tồn tại trong phiên bản `pyftpdlib` hiện cài. Đây là blocker môi trường, không phải lỗi contract; cần sửa dependency/test fixture trước khi xác nhận toàn suite.
- Phase 2 là bước tiếp theo: mở rộng schema/provider registry, rà soát secret response và migration tương thích.

### 2026-10-20 — Phase 2 đang thực hiện

- Đã mở rộng `PrinterProvider`/factory với `flashforge_ad5m` và `flashforge_creator5`; provider được nhận diện nhưng factory chưa bật client mạng.
- `PrinterCreate` yêu cầu serial/check code cho FlashForge, canonicalize model và validate `provider_options` JSON với HTTP/camera/TCP ports; Creator 5 bị từ chối TCP option.
- `PrinterResponse` scrub `access_code`/`auth_token`, chỉ trả `access_code_set`/`auth_token_set`; frontend type đã phản ánh provider mới và credential nullable.
- Check code dùng `auth_token` nhưng được mã hóa Fernet khi ghi FlashForge; API từ chối ghi nếu encryption helper rơi về plaintext. Startup migration mã hóa legacy FlashForge rows và không thay đổi token provider khác.
- Không cần schema migration vì `provider` là chuỗi và `provider_options` đã tồn tại; data migration mã hóa legacy FlashForge rows nhưng không đổi token provider khác.
- `test_printers_api.py` xác nhận create/PATCH/get/list: check code được mã hóa khi lưu và không xuất hiện trong response; probe nhận model và provider options đã chuẩn hóa. Encryption integration xác nhận migration chạy lặp không mã hóa lại.
- Verification: schema/contract/protocol/factory/provider đạt 116 tests qua `pytest --noconftest`; toàn bộ `test_printers_api.py` và secret migration integration đạt 127 tests. PostgreSQL test path chưa cấu hình trong môi trường.
- Trạng thái: Phase 2 **DONE** cho SQLite/application path. PostgreSQL vẫn là test gap nếu CI có dịch vụ DB tương ứng.

### 2026-10-21 — Hoàn thành Phase 3

- Đã bắt đầu HTTP/TCP primitives tách khỏi provider lifecycle; auth errors và transport errors không echo response body/credential.
- Fake HTTP transport và fake TCP socket đã xác nhận request shapes, multipart upload, code/error policy, multi-chunk read, busy và M602 release.
- `ruff check` và `compileall` cho các module/test protocol đạt; 30 protocol tests và tổng cộng 57 test FlashForge schema/contract/protocol đạt với `--noconftest`.
- Phase 2 lúc đó vẫn DOING do thiếu integration route/DB tests; regression tests sau đó được ghi ở mục Phase 2 hoàn tất bên dưới. Config pytest chuẩn tại `backend/tests/unit/services/` vẫn lỗi vì `services/conftest.py` import `TLS_FTPHandler` không có trong `pyftpdlib`.
- HTTP JSON and multipart were exercised against a local HTTP server; TCP cancellation and same-endpoint serialization were exercised against a local TCP server. Reference protocol is still inferred and has no physical firmware evidence.
- Discovery UDP/M115 sẽ làm ở Phase 11, upload `Expect: 100-continue` fallback sẽ làm ở Phase 8.
- Bước tiếp theo: hoàn tất CRUD/migration integration tests của Phase 2 rồi bắt đầu provider AD5M.

### 2026-10-21 — Phase 2 hoàn tất và Phase 4 đang thực hiện

- Hoàn tất route integration test: tạo AD5M với model/port, xác nhận probe nhận model và normalized provider options, đọc DB để kiểm tra check code dạng `fernet:`, đổi check code qua PATCH, rồi xác nhận GET/list không echo credential.
- Migration test chạy `_migrate_encrypt_legacy_secrets()` hai lần; giá trị FlashForge vẫn decrypt đúng và token Moonraker giữ nguyên.
- Đã thêm `flashforge_ad5m.py` với state tương thích Printbuddy, POST `/detail`, chuẩn hóa state/progress/layer/thời gian/nhiệt/quạt/firmware, scrub field serial/check code khỏi raw state và callback chuyển trạng thái.
- Factory giải mã check code tại provider boundary, nối AD5M vào `PrinterManager.test_connection` và truyền model/provider options từ Add Printer. Creator 5 hiện được nhận diện schema/provider ID nhưng factory cố ý từ chối, tránh dùng nhầm AD5M TCP 8899.
- File list dùng TCP M601/M661/M602; khi TCP lỗi dùng `/gcodeList` và lưu cờ `complete=false`, `source=http-recent`. API file route chưa hiển thị metadata completeness.
- Verification: `pytest --noconftest` FlashForge schema/contract/protocol/provider/factory đạt 115 tests; printer CRUD + secret encryption integration đạt 4 tests; Ruff, compileall và `git diff --check` đạt. Có Pydantic warnings không liên quan về protected namespace `model_*`.
- Môi trường pytest chuẩn cho unit services chưa thu thập được do `services/conftest.py` import `TLS_FTPHandler` không có trong phiên bản `pyftpdlib` hiện cài; test mục tiêu được chạy với `--noconftest`.
- Bằng chứng giao thức là source-derived + fake/local loopback; chưa có máy thật. Phase 4 tiếp tục với upload/start/job controls, reconcile status và capability/safety integration.

### 2026-10-21 — Phase 4 tiếp tục: upload/start/job controls và route path policy

- AD5M provider đã có upload riêng (`printNow=false`), start với leveling tùy chọn, kiểm tra trạng thái ban đầu/file listing và reconcile đến khi status xác nhận đúng filename đang chạy.
- Pause/resume/cancel kiểm tra trạng thái trước lệnh, rồi reconcile state; nếu response lệnh timeout thì chỉ đọc lại status, không gửi lệnh side-effect lần hai. Lỗi status poll đánh dấu provider disconnected.
- AD5M chỉ khai báo file ở thư mục gốc. Provider và API trả lỗi rõ ràng cho path lồng, storage selector, AMS mapping và platform selection; tránh upload basename nhưng đối chiếu/start nhầm file cùng tên trong thư mục khác.
- Dùng `PurePosixPath` cho remote paths để hành vi rename/reconcile không phụ thuộc hệ điều hành chạy Printbuddy.
- Bổ sung provider unit tests và route integration tests cho upload, path guard, start, job control và timeout reconcile.
- Verification: Ruff và `git diff --check` đạt; FlashForge provider/protocol/factory `97 passed`; file API integration `21 passed`; printer CRUD + secret encryption integration `127 passed`. Các integration tests phát sinh 5 Pydantic warnings hiện có về `model_*` protected namespace.
- Chạy integration qua pytest chuẩn có fixtures. Một lần chạy thử `--noconftest` cho integration không có fixture `async_client`; đây là cấu hình lệnh không hợp lệ, không phải test failure.
- Bằng chứng vẫn là source-derived + fake/local tests; chưa có máy FlashForge thật. AD5M thermal/fan/filtration/leveling/camera, API hiển thị completeness và full application smoke vẫn chưa hoàn thành; Phase 4 tiếp tục DOING.
- Bước kế tiếp: nối capability/diagnostics và expose file-list completeness/warning qua API; sau đó tiếp tục controls được protocol chứng minh. Không bật delete khi chưa có endpoint evidence.

### 2026-10-21 — Phase 4 tiếp tục: capability snapshot và listing diagnostics

- Thêm `capability_snapshot()` và `GET /printers/{id}/capabilities`. AD5M hiện báo status/upload/print/job/bed-leveling code paths đã nối, local files partial, nhiệt/quạt read-only; filtration/camera và các mục reference khác còn planned. Creator 5 chỉ hiện planned vì factory/provider chưa triển khai. Connector transport báo unavailable. Tất cả model vẫn `hardware_verified=false` và protocol evidence là `source_inferred`.
- File listing response thêm `listing.completeness` (`complete` hoặc `recent_only`), `source` và warning. Provider xóa metadata cũ trước lần poll mới để lỗi cả TCP và HTTP không giữ nhầm trạng thái completeness từ lần trước. Frontend API type đã cập nhật.
- `PrinterManager.test_connection` trả thông báo FlashForge riêng cho credential/LAN mode, timeout và command channel busy; diagnostic không echo exception hoặc secret.
- Verification: FlashForge/schema/protocol/factory/diagnostic unit selection `115 passed`; file API integration `23 passed`; Ruff và `git diff --check` đạt. `frontend/npm run build` đạt (TypeScript và Vite); Node `20.12.2` thấp hơn Vite khuyến nghị `20.19+`, đồng thời có cảnh báo bundle size. Integration có 5 Pydantic warnings hiện hữu về protected namespace `model_*`.
- Không có hardware run. Các capability `implemented` chỉ mô tả code path đã được nối và fake-tested; không khẳng định firmware đã xác nhận. Phase 4 vẫn DOING.
- Bước tiếp theo: xác minh payload fan/filtration từ source trước khi code; giữ camera, filtration và delete unavailable/planned nếu semantics điều khiển hoặc safety chưa đủ rõ.

### 2026-10-21 — Phase 4 tiếp tục: nozzle và bed temperature

- AD5M provider có `set_nozzle_temperature()` và `set_bed_temperature()` dùng `temperatureCtl_cmd` lần lượt với `rightNozzle` và `platform`, theo payload ghi trong reference. Target được validate bằng `contract.nozzle_max_c`/`bed_max_c` (AD5M 265/110 °C); giá trị ngoài range bị từ chối trước network call.
- Control yêu cầu status đọc được và state IDLE/RUNNING/PAUSE/FINISH. Sau lệnh, provider poll `/detail` bounded để xác minh target; timeout/error chỉ trigger readback, không gửi lệnh lần hai. Route chạy FlashForge control trong worker thread để polling không block event loop.
- Capability snapshot đánh dấu nozzle/bed là `implemented` code paths. Bằng chứng firmware vẫn `source_inferred`, `hardware_verified=false`.
- Verification sau bước này: FlashForge/contract/protocol/factory/diagnostic unit selection `119 passed`; file + temperature control route integration `24 passed`; Ruff và `git diff --check` đạt. Integration có 5 Pydantic warnings hiện hữu về protected namespace `model_*`. `frontend/npm run build` đã đạt ở bước trước.
- Bước kế tiếp: xác minh thêm command/payload cho fan và filtration trước khi bật control; sau đó cần hardware smoke trước khi nâng hardware verification. Camera stream và delete tiếp tục unavailable cho tới khi semantics rõ.

### 2026-10-21 — Phase 4 tiếp tục: cooling/chamber fan controls

- Đối chiếu reference tại Print-Farm-Controller commit `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`: `printerCtl_cmd` dùng field `coolingFan` và `chamberFan`. Đây là bằng chứng source-derived, chưa phải firmware evidence.
- AD5M provider thêm `set_fan_speed(fan, speed)`, giới hạn 0-100%, yêu cầu status/state hợp lệ trước lệnh và poll `/detail` để xác nhận tốc độ sau lệnh. Timeout chỉ reconcile status, không gửi lệnh điều khiển lần hai.
- Các alias cooling/part/model và chamber/box được map tới hai fan tương ứng; `aux` cùng các fan không được hỗ trợ bị từ chối. Existing fan-speed API route được tái sử dụng.
- Capability snapshot đánh dấu cooling/chamber fan là `implemented` cho direct AD5M code path. `hardware_verified=false`; filtration, camera stream và file delete vẫn không được bật.
- Verification: AD5M provider + FlashForge contract unit tests `34 passed`; FlashForge controls API integration `2 passed`; Ruff và `git diff --check` đạt. Integration còn 5 Pydantic warnings hiện hữu về protected namespace `model_*`.
- Không có máy thật/emulator firmware run; kết quả chỉ xác nhận fake-tested code path và payload suy ra từ mã nguồn tham khảo. Phase 4 tiếp tục DOING.
- Bước kế tiếp: nối camera AD5M vào effective camera source và activation/stop lifecycle của proxy; filtration chờ firmware readback/state evidence. Sau đó chạy hardware smoke cho direct AD5M. Không nâng `hardware_verified` khi chưa có bằng chứng trên máy thật.

### 2026-10-21 — Phase 4 tiếp tục: đánh giá filtration readback

- Đọc trực tiếp `src/printer-api.js` tại Print-Farm-Controller commit `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`: `setFiltration()` gửi `circulateCtl_cmd` với `internal`/`external` là `open` hoặc `close`, rồi trả kết quả lệnh.
- `getStatus()` chỉ lấy `/detail` và chuẩn hóa status chung; adapter không đọc hoặc xác nhận trạng thái filter. Không có evidence trong commit này về ACK timeout reconciliation, idempotency hoặc safety interlock riêng cho filtration.
- Giữ AD5M `filtration` ở capability `planned`; contract test hiện có bảo đảm trạng thái này. Không thêm endpoint/provider command cho tới khi có readback/state sample từ firmware và policy vận hành.
- Cập nhật `docs/flashforge-integration-reference.md` để phân biệt command acceptance với trạng thái filter đã xác minh.
- Verification: `pytest -q --noconftest backend/tests/unit/services/test_flashforge_contract.py` đạt `12 passed`; Ruff và `git diff --check` đạt. Chưa có firmware/emulator hay máy thật để xác nhận.
- Bước kế tiếp: kiểm tra camera proxy, URL validation, stream fan-out và quyền truy cập trước khi quyết định tích hợp MJPEG FlashForge.

### 2026-10-21 — Phase 4 tiếp tục: đánh giá camera proxy

- `backend/app/api/routes/camera.py` đã có provider-neutral external MJPEG stream path, stream-token permission gate, URL-derived input, fan-out broadcaster, disconnect cleanup, snapshot reuse và stream status.
- `backend/app/services/external_camera.py` sanitize URL trước khi mở MJPEG upstream; không cần tạo proxy thứ hai cho FlashForge.
- `get_effective_camera_source()` hiện derive camera source cho PrusaLink/Creality/Elegoo, chưa cho FlashForge. Camera route chỉ chủ động kích hoạt phiên camera của Elegoo; FlashForge reference yêu cầu `streamCtrl_cmd {action:"open"}` trước stream. URL có thể lấy từ `/detail.cameraStreamUrl`, nếu thiếu dùng `http://{printer_host}:8080/?action=stream`.
- Giữ FlashForge camera capability `planned`: còn thiếu effective-source mapping, activation và cleanup policy cho stream lifecycle, cùng kiểm thử camera/permission/status/snapshot/stop. Chưa thay đổi route chung.
- Bước triển khai tiếp: thêm source derivation an toàn cho FlashForge và activation trong vòng đời fan-out mà không ảnh hưởng external camera hoặc Elegoo behavior. Reference chưa ghi command đóng camera; cleanup hiện chỉ được teardown upstream proxy, không suy diễn lệnh firmware close. Sau đó bổ sung tests cho auth, disconnect/stop cleanup, URL fallback và activation failure.

### 2026-10-21 — Phase 4 tiếp tục: AD5M camera qua proxy

- `get_effective_camera_source()` derive MJPEG URL cho direct AD5M từ validated `camera_port` (mặc định 8080); manual external camera vẫn ưu tiên, Connector không bị truy cập trực tiếp.
- AD5M provider có `activate_camera()`: kiểm tra status/state trước lệnh `streamCtrl_cmd {action:"open"}`, gửi lệnh tối đa một lần, reconcile `/detail` sau lỗi, chỉ nhận `cameraStreamUrl` cùng host và port đã cấu hình; khi API ACK nhưng không có URL status thì dùng fallback `/?action=stream`.
- Snapshot, camera test/diagnose và live MJPEG route dùng provider activation. Live stream tiếp tục qua external-camera proxy hiện có, token auth, URL sanitizer và broadcaster; disconnect/stop đóng upstream. Không gửi firmware close vì reference không ghi payload đóng camera.
- Capability snapshot đánh dấu camera `implemented` cho direct AD5M code path; `hardware_verified=false`, giao thức vẫn `source_inferred`.
- Verification: FlashForge provider + camera-source + contract unit tests `57 passed`; camera API integration `45 passed`; Ruff và `git diff --check` đạt. Có 1 warning Pydantic ở unit selection và 5 warning `model_*` ở integration, đều là warnings hiện hữu.
- Chưa có emulator/firmware hoặc máy thật để xác nhận camera URL, độ trễ hình đầu tiên, hành vi camera sau khi proxy dừng, hay stop/reconnect trên AD5M thực tế.
- Bước kế tiếp: tách nghĩa capability leveling trước print khỏi calibration độc lập; sau đó hardware smoke direct AD5M cho stream/snapshot/start-stop và tiếp tục Creator 5. Không nâng `hardware_verified` trước khi có bằng chứng trên máy thật.

### 2026-10-21 — Phase 4 tiếp tục: tách bed leveling trước print và calibration độc lập

- Route chung `POST /printers/{id}/calibration` gọi `client.start_calibration(...)`; AD5M provider không có method này. Mã nguồn tham chiếu có command `calibration_cmd` cho leveling độc lập, nhưng chưa có state readback để reconcile hoàn tất hay phát hiện thất bại sau ACK.
- Tách capability `bed_leveling_before_print` (đã nối trong `printGcode.levelingBeforePrint`) khỏi `bed_leveling` (calibration độc lập). Snapshot AD5M báo capability trước print `implemented`, còn calibration độc lập `planned`.
- Route calibration từ chối rõ FlashForge trước khi gửi lệnh. Thao tác leveling trước print vẫn dùng luồng hiện có. Các provider khác không đổi.
- Verification: `pytest -q --noconftest backend/tests/unit/services/test_flashforge_contract.py` đạt `12 passed`; `pytest -q --noconftest backend/tests/unit/services/test_flashforge_ad5m_provider.py` đạt `26 passed`; `pytest -q backend/tests/integration/test_flashforge_controls_api.py` đạt `3 passed`; capability API selection đạt `1 passed`; Ruff và `git diff --check` đạt. Integration có 5 warning Pydantic protected namespace `model_*` hiện hữu.
- Bằng chứng giao thức vẫn `source_inferred`; không có emulator/firmware hay máy thật. Phase 4 tiếp tục DOING.
- Bước tiếp theo: chạy test capability/API và Ruff, rồi tiếp tục rà Creator 5 direct protocol theo phase 5; hardware smoke AD5M vẫn là blocker cho hardware verification.

### 2026-10-21 — Phase 5: status và recent-file path Creator 5

- Đọc lại `creator5-api.js` tại commit tham chiếu. Creator 5 chuẩn hóa bốn nozzle và bốn material slots; `currentSlot` là slot đang cấp vật liệu, không phải active tool. Nếu nhiều nozzle target cùng bật thì active tool phải để unknown.
- File API chỉ trả recent files; không có TCP M661 path cho Creator 5. Nhiệt dùng mảng bốn nozzle với sentinel `-200`; chamber chỉ dành cho Creator 5 Pro. `msConfig_cmd` có material/color allowlist và readback polling trong adapter nguồn.
- Thêm `flashforge_creator5.py` và đăng ký factory riêng, dùng shared HTTP client nhưng không khởi tạo TCP. Status ánh xạ bốn nhiệt nozzle sang `nozzle`...`nozzle_4`; `currentSlot` nằm ở material-station raw data riêng và không ảnh hưởng active tool. Chỉ chọn active tool nếu đúng một target nozzle khác 0.
- Creator 5 trả recent file list qua HTTP, đánh dấu `complete=false`, `source=http-recent`; chỉ root listing được nhận. Credential keys trong detail/response bị scrub khỏi state public.
- Runtime capability Creator 5 lúc đầu chỉ nâng `status=implemented`, `local_files=partial`; capability được mở rộng theo từng bước kiểm soát phía dưới. `PrinterManager` lifecycle dùng chung state/callback contract.
- Chưa port logic `materialMappings`/default PLA và màu từ nguồn: cần đối chiếu với contract tool-map của Printbuddy để không tự đoán vật liệu/mapping. Camera direct hiện có activation/readback; ACK không được coi là bằng chứng URL hoặc stream đã hoạt động.
- Verification: Creator 5 provider unit `4 passed`; FlashForge provider/factory/contract unit `96 passed`; status/files/capability API integration `2 passed`; Ruff check đạt. `ruff format --check` còn báo một số file nền tảng/đã chỉnh trước đó chưa format theo formatter hiện tại; hai file mới đã được format. Integration có 5 warning Pydantic `model_*` hiện hữu.
- Bằng chứng vẫn là source-inferred + fake/API tests; chưa có emulator/firmware hay máy thật. Phase 5 tiếp tục DOING.
- Thêm Creator 5 nozzle/bed temperature control: pre-read status/state gate, gửi `temperatureCtl_cmd` một lần (nozzle dùng mảng bốn phần tử và sentinel `-200`, bed dùng `platform`), rồi poll `/detail` để xác nhận target. Sau lỗi/timeout chỉ đọc lại, không gửi lại command.
- Route nozzle nhận `extruder=0..3` cho Creator 5 (mặc định 0); model limits 320°C nozzle/120°C bed enforce ở route và provider. Runtime capability nâng `nozzle_temperature`, `tool_temperatures`, `bed_temperature` lên `implemented` chỉ cho direct Creator 5. Connector vẫn unavailable.
- Verification: Creator 5 provider tests `9 passed`; FlashForge provider/factory/contract group `101 passed`; controls integration `4 passed`; capability/status/files integration assertions được cập nhật; Ruff check, changed-test format check và `git diff --check` đạt. Integration có 5 warning Pydantic `model_*` hiện hữu. Một lần format check trên các file đã tồn tại báo một số đoạn cũ trong route/contract chưa formatted; không format lại các phần ngoài phạm vi.
- Bằng chứng vẫn `source_inferred` + fake/API tests; chưa có emulator/firmware hay máy thật. Phase 5 tiếp tục DOING.
- Bước tiếp: triển khai Creator 5 chamber control riêng Pro với gate model/readback, sau đó material configuration (allowlist + status readback). Upload/start cần xác định multipart headers và reconcile; hardware verification AD5M vẫn chưa có.

### 2026-10-21 — Phase 5 tiếp tục: chamber Pro và material configuration

- Creator 5 Pro chamber đã có code path: `temperatureCtl_cmd {chamber: target}`, model gate qua `chamber_max_c=65`, pre-read status, bounded readback và API riêng; Creator 5 thường/Connector bị từ chối. Fake API client được bổ sung method còn thiếu để kiểm tra route integration.
- Đọc `src/creator5-api.js` tại reference commit `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`: danh sách 21 material và 24 mã màu hex; `msConfig_cmd` dùng slot 1-based, chỉ khi idle, giữ trường hiện tại nếu chỉ đổi material hoặc color, đọc lại tối đa 3 lần.
- Creator 5 provider thêm `set_filament_config()` với allowlist đóng, validation tool 0-3, idle precheck, một lần gửi command và tối đa ba lần readback. Nếu metadata hiện tại không đủ để tạo payload đầy đủ thì từ chối trước khi gửi; ACK không được xem là thành công nếu readback không khớp.
- Thêm `POST /printers/{id}/filament-config` (permission `printers:control`, direct Creator 5 only), request schema, typed API client và capability status cho material status/type/color control.
- Verification: Creator 5 provider + contract unit `29 passed`; FlashForge controls API `6 passed`; Creator 5/capability integration selection `12 passed` (18 deselected); Ruff, `npx tsc --noEmit` và `git diff --check` đạt. Integration có 5 Pydantic protected-namespace warnings hiện hữu.
- Chưa có emulator/firmware/máy thật; giao thức vẫn `source_inferred`, `hardware_verified=false`. Phase 5 vẫn DOING.
- Bước tiếp: xác minh upload/start/job command + multipart headers/readback của Creator 5, đồng thời đối chiếu tool-map Printbuddy trước khi bật `materialMappings`. Không dùng mapping/default PLA từ reference để suy đoán yêu cầu file local.

### 2026-10-21 — Phase 5 tiếp tục: Creator 5 upload, start và job controls

- Đối chiếu `creator5-api.js`, `flashforge-creator5-adapter.js` và `upload-gcode.js` tại reference commit: upload multipart qua `/uploadGcode`, file field `gcodeFile`, `printNow=false`, material-station headers; start qua `/printGcode` với leveling/flow calibration/timelapse; job control `jobCtl_cmd` actions pause/continue/cancel.
- HTTP client tách timeout upload 300 giây khỏi timeout JSON 8 giây. Chưa thêm `Expect: 100-continue` handshake/fallback; đó vẫn là protocol-library task Phase 8.
- Creator 5 upload nhận `tool_count` 1-4 (mặc định 1), đẩy `useMatlStation`, `gcodeToolCnt`, `flowCalibration` và `timeLapseVideo`; file được start riêng. Route xác nhận tên xuất hiện trong HTTP recent list, nhưng size không có nên đây không phải integrity verification đầy đủ.
- Start kiểm tra root filename, trạng thái IDLE/FINISH/FAILED và file có trong recent list; sau một lần `/printGcode`, bounded status readback phải xác nhận RUNNING đúng file. AMS mapping/platform selection bị từ chối vì chưa có tool-map contract.
- Pause/resume/cancel kiểm tra state trước command, gửi đúng một `jobCtl_cmd`, rồi poll status đến state đích; command timeout/ACK không gây gửi lại side-effect.
- Capability direct Creator 5 nâng `file_upload`, `print_local_file`, `job_control`, `bed_leveling_before_print`, flow calibration, timelapse và camera khi code paths đã nối. Local files vẫn partial; print tool mapping còn planned.
- Verification: Creator5 provider/contract/protocol unit `70 passed`; FlashForge controls + Creator5/capability API integration selection `13 passed`; Ruff, TypeScript và `git diff --check` đạt. Năm Pydantic warnings protected namespace vẫn hiện hữu.
- Chưa có firmware/emulator/máy thật; `hardware_verified=false`, evidence `source_inferred`. Phase 5 tiếp tục DOING.
- Bước tiếp: hoàn tất hardware/protocol smoke nếu có Creator 5/Pro; rà contract slicer metadata của Printbuddy để thiết kế tool-map an toàn; sau đó camera lifecycle. Không bật mapping multi-tool hay cho upload UI tự đoán tool count từ file name.

### 2026-10-21 — Phase 5 tiếp tục: Creator 5 direct camera và tool-map audit

- Đã rà `threemf_tools.py`, slicer conversion, archive/queue và các chỗ dùng extruder metadata. Parser 3MF hiện có đọc metadata kiểu Bambu/Orca (một số hàm chỉ trả tập extruder được dùng), nhưng queue/start Creator 5 không nhận một tool-map contract do slicer sở hữu và giữ xuyên suốt. Chưa có nguồn đủ tin cậy để ánh xạ tool của file local sang slot Creator 5; `materialMappings` và `print_tool_mapping` tiếp tục planned, start từ chối mapping.
- Creator 5/Pro direct camera source lấy host cùng `camera_port` đã validate; Connector không derive endpoint. Provider kiểm tra status, gửi `streamCtrl_cmd {action:"open"}` tối đa một lần, đọc lại `/detail.cameraStreamUrl`, chỉ chấp nhận HTTP cùng host và port; fallback `/?action=stream` chỉ khi command được chấp nhận. Camera dùng snapshot/live proxy, auth token và fan-out hiện hữu. Khi viewer dừng, proxy teardown upstream; không phát firmware close command chưa được xác nhận.
- Queue scheduler và background dispatch không còn tính AMS mapping Bambu cho Creator 5. Nếu queue/reprint truyền `ams_mapping` hoặc `print_platform_type`, job bị từ chối trước upload với lỗi rõ ràng. `gcodeToolCnt` được truyền từ số `slot_id` đã dùng trong `slice_info.config` (1-4); G-code thuần hoặc metadata không đọc được giữ mặc định 1, không suy đoán từ tên file hay `tool_count` của máy.
- Capability snapshot nâng camera Creator 5 direct lên `implemented` như AD5M; vẫn `protocol_evidence=source_inferred`, `hardware_verified=false`. Connector camera relay còn unavailable/planned.
- Verification: Creator 5 + camera-source + contract unit `64 passed`; camera API FlashForge snapshot/live cho AD5M và Creator 5 `4 passed`; scheduler/background provider-upload tests `14 passed`; Ruff đạt. Có một warning Pydantic `model_pictures` ở unit và 5 warning protected namespace trong integration, hiện hữu ngoài phạm vi.
- Chưa có máy thật/emulator. Chưa xác nhận firmware Creator 5/Pro thực tế có cùng `streamCtrl_cmd`, URL, khả năng stream sau proxy stop, hay behavior reconnect. Không nâng hardware verification.
- Bước tiếp theo: physical smoke Creator 5 và Pro (camera, upload/start/job controls, bốn nozzle, material slots); sau đó thiết kế tool-map contract từ dữ liệu slicer có nguồn rõ ràng, giữ mapping tắt tới khi contract và tests hoàn chỉnh.

### Mẫu cập nhật sau mỗi bước

Ngày/giờ:
Phase/task:
Trạng thái trước -> sau:
Files changed:
Tests/checks:
Evidence (emulator/firmware/model):
Blocker/risk:
Next step:

### 2026-10-21 — Phase 12: Connector FlashForge temperature controls

- Thêm `printer.temperature.request/result`; request giữ credential chỉ trong memory, thêm model để phân biệt Creator 5 Pro và extruder index.
- Connector thực hiện pre-read `/detail`, gate trạng thái, một `temperatureCtl_cmd`, rồi poll readback bounded. Timeout không retry side-effect.
- Payload đã nối theo model: AD5M `rightNozzle`/`platform`; Creator 5 `nozzles` bốn phần tử với sentinel `-200`; chamber chỉ Creator 5 Pro đến 65°C. Không mở TCP Creator 5.
- Backend gateway whitelist, transport và route nozzle/bed/chamber dùng Connector; không fallback sang `PrinterManager`, không trả check code/raw body.
- Trạng thái: Phase 12 temperature `TODO` -> `DOING`; chưa đánh dấu hoàn tất integration route vì mới có unit + nhóm integration Connector hiện hữu.
- Verification: `19 passed` cho fake HTTP/agent/transport temperature; `5 passed` nhóm integration Connector/printer; compileall, Ruff và `git diff --check` đạt. Warnings Pydantic protected namespace là hiện hữu.
- Evidence: `source_inferred`, `hardware_verified=false`; chưa có firmware capture, emulator hoặc máy FlashForge thật.
- Rủi ro: command field/readback names và Creator 5 Pro chamber behavior chưa được physical-tested; route integration riêng cho ba heater và gateway validation cần bổ sung.
- Đã bổ sung integration route: Creator 5 Pro nozzle qua RPC với extruder index, Creator 5 thường chamber bị từ chối trước RPC, không gọi `PrinterManager` và không trả credential; gateway đã validate `printer.temperature.result`.
- Bước tiếp theo: cải thiện bounded polling job control và physical smoke nếu có máy; giữ `source_inferred`/`hardware_verified=false`.

### 2026-10-21 — Phase 11: chốt parser FlashForge discovery

- Đọc lại `discovery.js` và `discovery-network.js` tại commit tham chiếu `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`, xác nhận layout modern 276-byte (name, command/event port, vendor/product/PID, status, product type, LAN mode, serial), legacy 140-byte và fallback TCP `~M115`.
- Thêm package thuần `flashforge_discovery` không mở socket: parser trả identity/endpoint đã chuẩn hóa, map PID cho AD5M/Creator 5 và giữ model/port/serial thiếu ở trạng thái unknown. Creator 5 không được coi `command_port=8899` là capability TCP.
- Thêm 6 unit tests với fixture tổng hợp: modern AD5M, modern Creator 5 Pro, legacy unknown, packet ngắn, M115 AD5M hợp lệ và M115 không hợp lệ.
- Trạng thái trước -> sau: Phase 11 `TODO` -> `DOING`; parser contract đạt, network discovery chưa nối.
- Verification: `pytest -q --noconftest backend/tests/unit/test_flashforge_discovery_parser.py` (`6 passed`); Ruff đạt; `git diff --check` đạt.
- Evidence: chỉ source-inferred + fixture tổng hợp; chưa có firmware capture, emulator hoặc máy FlashForge thật. Không nâng `hardware_verified`.
- Rủi ro còn lại: layout và event-port semantics chưa được xác thực trên firmware; legacy packet không đủ dữ liệu để chọn provider; UDP multicast/broadcast và M115 probe phải được bounded trước khi bật.
- Bước tiếp theo: nối parser vào Connector discovery với provider/port allowlist, subnet private bounded, timeout/concurrency giới hạn và kết quả không chứa credential; sau đó mới cân nhắc direct transport.

### 2026-10-21 — Phase 11/12: nối parser vào Connector UDP discovery

- `connector/discovery.py` gọi parser dùng chung khi request chứa một trong các cổng discovery `8899`, `19000`, `48899`; socket blocking chạy trong worker thread, gửi multicast `225.0.0.9` và unicast/directed broadcast trong private CIDR đã giới hạn.
- Probe TCP tổng quát loại các cổng FlashForge để không trả Creator 5 như TCP capability chỉ vì máy quảng bá command port. Kết quả FlashForge ưu tiên HTTP `8898`, kèm provider/model/serial đã lọc; model không xác định không bị suy đoán.
- Mở rộng wire entry với các field tùy chọn `provider`, `model`, `serial_number`; serializer bỏ `null` để payload Bambu/legacy giữ hình dạng cũ. Docker Connector copy package parser dùng chung.
- Thêm test bounded UDP socket, Creator 5 command-port guard và TCP probe filtering. Trạng thái Phase 11 giữ `DOING`; Phase 12 `TODO` -> `DOING` cho discovery FlashForge riêng, verify/control/status/files vẫn chưa làm.
- Verification: nhóm parser + Connector discovery/agent `16 passed`; Ruff đạt; `git diff --check` đạt.
- Evidence: source-inferred + fake socket/fixture; chưa có packet capture firmware, emulator hoặc máy thật. Không nâng `hardware_verified`.
- Fallback TCP `~M115` đã nối bounded cho AD5M khi UDP không trả kết quả; chỉ chấp nhận `Machine Type` FlashForge Adventurer 5M + `SN`, không nhận Creator 5. Directed broadcast có thể bị hệ điều hành/container chặn; `eventPort` dùng làm HTTP theo mã tham chiếu nhưng chưa xác thực firmware.
- Verification bổ sung: parser + Connector discovery/agent `17 passed`; Ruff và `git diff --check` đạt. Cần physical/network smoke trước khi bật mặc định trong UI.
- Connector provider verification nhận `flashforge_ad5m`/`flashforge_creator5`, POST `/detail` với credentials chỉ trong memory, yêu cầu `code == 0`, không trả body/secret. Add Printer UI gửi các cổng FlashForge, chọn endpoint sẽ điền provider/model/serial/HTTP port; không tự lưu máy.
- Verification: discovery/provider/transport nhóm liên quan `31 passed`; Ruff, `git diff --check` và `frontend/node_modules/.bin/tsc.cmd --noEmit` đạt. Có 1 Pydantic warning `model_pictures` hiện hữu.
- Evidence: source-inferred + fake socket/HTTP; chưa có packet capture firmware, emulator hoặc máy thật. Không nâng `hardware_verified`.
- Connector status FlashForge nhận serial/check code trong request ngắn hạn, đọc `/detail`, chuẩn hóa state/progress/filename/temperatures/firmware và loại credential khỏi telemetry; Bambu/Klipper/Prusa vẫn dùng reachability probe.
- Verification bổ sung: FlashForge/provider/Connector group `102 passed`; Ruff, `git diff --check` và TypeScript `tsc --noEmit` đạt. Có 1 Pydantic warning `model_pictures` hiện hữu.
- Evidence: source-inferred + fake socket/HTTP; chưa có packet capture firmware, emulator hoặc máy thật. Không nâng `hardware_verified`.
- Bước tiếp theo: nối Connector control/file transfer theo RPC mới, bắt đầu từ read-only file listing; direct LAN discovery vẫn giữ capability-unavailable tới khi có route/service contract/test riêng.

### 2026-10-21 — Phase 12: Connector read-only file listing FlashForge

- Thêm `printer.files.request/result` vào `connector_protocol`; request nhận IP, provider, HTTP/TCP port, serial/check code, root path và timeout. Credential chỉ tồn tại trong request memory, không xuất hiện trong result.
- Connector AD5M ưu tiên TCP `M601` -> `M661` -> `M602`, có giới hạn response và fallback `/gcodeList` khi TCP lỗi. Creator 5/Pro chỉ dùng HTTP `/gcodeList`, tuyệt đối không mở TCP 8899.
- Chuẩn hóa entry thành `name/path/type/size`, giới hạn 256 file và đánh dấu `complete` hoặc `recent_only` cùng `source`; không trả raw firmware body.
- Backend transport và `GET /printers/{id}/files` đã nối Connector path cho FlashForge, giữ direct provider path cũ; connector provider khác trả capability rõ ràng.
- Verification: Connector file/agent/transport + protocol/provider group `48 passed`; read-only file regression group `13 passed`; Connector/printer integration selection `4 passed`; Ruff và `git diff --check` đạt. Cảnh báo Pydantic `model_*` hiện hữu.
- Evidence vẫn `source_inferred` + fake TCP/HTTP; chưa có firmware capture, emulator hoặc máy thật. Không nâng `hardware_verified`.
- Rủi ro: M661 response framing, event-port semantics và HTTP recent-list shape chưa được xác thực trên firmware thực; route file listing Connector hiện chỉ read-only, upload/control RPC chưa nối.
- Bước tiếp theo: bổ sung integration test route Connector file listing và sau đó thiết kế RPC upload với multipart streaming, giữ Creator 5 không dùng TCP.

### 2026-10-21 — Phase 12: Connector chunked upload FlashForge

- Thêm `printer.upload.request/result` với ba phase `begin/chunk/finish`; backend đọc file theo chunk 96 KiB, mỗi frame vẫn dưới giới hạn WebSocket và Connector ghi tạm tối đa 512 MiB.
- Connector xác nhận thứ tự chunk, kích thước khai báo, phần mở rộng file và dọn file tạm khi lỗi/kết thúc. Khi đủ file, AD5M và Creator 5 đều upload qua HTTP `/uploadGcode`; Creator 5 giữ các header material-station và không dùng TCP.
- Backend `ConnectorPrinterTransport.upload_file()` truyền tên file đích thật, credential chỉ trong request memory; route upload FlashForge Connector chỉ root path, conflict strategy `error`, chưa bật rename/delete-replace.
- Verification: upload/transport/agent/files unit `16 passed`; route Connector file/status/upload integration `3 passed`; Ruff, compileall và `git diff --check` đạt. Cảnh báo Pydantic `model_*` hiện hữu.
- Evidence vẫn `source_inferred` + fake TCP/HTTP/gateway; chưa có firmware capture, emulator hoặc máy thật. Không nâng `hardware_verified`.
- Rủi ro: upload retry sau mất kết nối chưa có resume protocol; Connector restart sẽ mất session tạm; multipart response shape chưa xác thực trên firmware thật.
- Bước tiếp theo: nối RPC start/pause/resume/cancel qua Connector, mỗi command một lần và bắt buộc status readback trước/sau.

### 2026-10-21 — Phase 12: Connector FlashForge job control

- Thêm `printer.control.request/result` cho `start`, `pause`, `resume`, `cancel`. Connector đọc `/detail` trước, kiểm tra trạng thái hợp lệ, gửi đúng một HTTP command (`/printGcode` hoặc `jobCtl_cmd`), rồi đọc `/detail` sau để xác nhận.
- Backend transport và các route start/pause/resume/stop đã dùng Connector khi `connection_mode=connector`; không fallback sang `PrinterManager`. Credential chỉ truyền trong request memory và không trả về.
- Start Connector chỉ nhận file root, không storage/AMS/tool mapping; Creator 5 vẫn giữ các tùy chọn flow/timelapse ở mức mặc định an toàn.
- Verification: control/agent/transport unit `14 passed`; Connector printer integration selection `4 passed`; Ruff, compileall và `git diff --check` đạt. Cảnh báo Pydantic `model_*` hiện hữu.
- Evidence vẫn `source_inferred` + fake HTTP/gateway; chưa có firmware capture, emulator hoặc máy thật. Không nâng `hardware_verified`.
- Rủi ro: status readback hiện là một lần đọc ngay sau command, chưa có polling delay/retry như direct provider; command timeout có thể để trạng thái thực tế chưa rõ nhưng không tự gửi lại.
- Bước tiếp theo: thêm bounded polling readback và kiểm tra route speed/temperature/chamber qua Connector, sau đó physical smoke cho job lifecycle.

### 2026-10-21 — Phase 12: bounded job-control readback qua Connector

- Sau pre-read/state gate và đúng một lệnh side-effect, Connector poll `/detail` tối đa 5 lần, cách nhau 350 ms. Poll chỉ đọc; không gửi lại lệnh kể cả khi ACK/readback timeout.
- Start yêu cầu state `RUNNING` và filename khớp tên file đã yêu cầu; pause/resume/cancel yêu cầu state đích tương ứng.
- Trạng thái: bounded control readback `TODO` -> `DONE` ở mức code/fake HTTP; physical smoke vẫn chưa thực hiện.
- Verification: control + agent + transport unit `17 passed`; direct provider job-control regression `8 passed`; Connector pause route integration `1 passed`; compileall, Ruff và `git diff --check` đạt. Warnings Pydantic protected namespace hiện hữu.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; không có firmware capture, emulator hoặc máy FlashForge thật.
- Bước tiếp theo: physical smoke khi có phần cứng, hoặc rà capability Connector tiếp theo đang thiếu; giữ cảnh báo rằng firmware có thể cập nhật trạng thái muộn hơn khoảng polling hiện tại.

### 2026-10-21 — Phase 12: capability snapshot theo transport Connector

- Cập nhật `capability_snapshot(..., direct_transport=False)` để không còn báo mọi thao tác Connector là `unavailable` sau khi RPC tương ứng đã được nối.
- Connector hiện báo `implemented` cho status, upload, print local file, job control, nozzle/bed temperature, bed-leveling-before-print; local files là `partial`. Creator 5 có tool temperatures; chamber temperature chỉ xuất hiện cho Creator 5 Pro.
- Camera, fan, filtration, material configuration, file delete, directory/storage navigation và tool/platform mapping vẫn unavailable trong Connector path.
- Verification: FlashForge contract unit `13 passed`; capability API integration `1 passed`; compileall và Ruff đạt. Pydantic warnings protected namespace hiện hữu.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; capability `implemented` chỉ mô tả code path đã có, không xác nhận hành vi firmware thực tế.
- Bước tiếp theo: physical smoke khi có phần cứng; nếu chưa có, tiếp tục rà soát safety/timeout contract và Connector RPC coverage.

### 2026-10-21 — Phase 12: tổng deadline cho side-effect RPC

- Thêm deadline tổng theo `timeout_ms` cho Connector job-control và temperature, bao trùm pre-read, một command và polling readback; mỗi poll không còn được phép tiêu toàn bộ timeout riêng rồi cộng dồn.
- Timeout sau khi gửi command trả lỗi sanitize, không gửi lại side-effect. Caller cần status request mới nếu muốn phân giải trạng thái thật.
- Verification: Connector control/temperature/agent/transport + contract unit `36 passed`; Connector pause/temperature/capability integration filter `4 passed`; Ruff và compileall đạt.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; test fake HTTP không xác minh thời gian phản hồi/semantics firmware.
- Bước tiếp theo: physical smoke nếu có máy; nếu chưa, review response correlation, cancellation và timeout handling trên các RPC FlashForge.

### 2026-10-21 — Phase 12: Connector upload delivery-unknown reconciliation

- Khi upload FlashForge qua Connector timeout/disconnect sau khi send, API thực hiện một request file-list read-only và đính kèm trạng thái `observed`/`not_observed`/`unavailable`, `completeness`, `source` và `integrity=unverified` cùng request ID gốc.
- Kết quả vẫn HTTP 504 `delivery_unknown` kể cả khi filename xuất hiện. Không retry upload và không coi tên file là bằng chứng integrity; AD5M M661 có listing complete theo code path nhưng không có size/hash, Creator 5 HTTP listing là recent-only.
- File Manager làm mới danh sách và cảnh báo người dùng kiểm tra trước khi retry; cảnh báo có khóa dịch đủ 10 locale.
- Verification: integration route upload unknown với AD5M complete listing, Creator 5 recent-only thấy/không thấy file và start unknown regression `4 passed`; Ruff và i18n parity đạt; `npm run build` (TypeScript + Vite) đạt. Vite cảnh báo Node `20.12.2` dưới mức yêu cầu khuyến nghị `20.19+` và JS bundle >3 MB.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; file-list fake integration không xác thực firmware, size hay nội dung thật.
- Bước tiếp theo: API truy vấn reconciliation theo request ID chỉ cần thiết nếu UI cần theo dõi lại sau lần snapshot; hiện UI refresh file list ngay. Sau đó tiếp tục safety/RPC audit và physical smoke AD5M/Creator 5/Pro khi có phần cứng. Không đánh dấu Phase 12 hoàn tất.

### 2026-10-21 — Phase 12: Connector upload destination and filename guard

- Audit phát hiện `upload_to_flashforge()` tạo HTTP URL trực tiếp nhưng thiếu `validate_private_endpoint()`, trong khi control, temperature và file listing đã enforce private LAN. Thêm guard private IP/port trước khởi tạo HTTP client; hostname và địa chỉ public bị từ chối.
- `UploadSession` giờ yêu cầu filename là basename, từ chối path dùng `/` hoặc `\\` trước khi chuyển thành multipart filename. Backend vẫn chuẩn hóa tên như trước; đây là guard ở ranh giới Connector.
- Verification: upload unit + agent upload selection `14 passed` (7 deselected); upload delivery-unknown route regression `3 passed`; Ruff, compileall và `git diff --check` đạt.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; chưa thực hiện network test với máy thật.
- Session binding được rà: `UploadSession` giữ request của `begin` làm destination và `finish` chỉ dùng request đã giữ; phase sau không thể đổi endpoint, credential hoặc filename. Duplicate begin không xóa session gốc; chunk index/declared size được kiểm tra; finish dọn staging trong `finally`; abort, TTL và disconnect đều dọn session.
- Thêm regression test gửi `finish` với IP/provider/serial/check code/filename đã sửa, xác nhận upload vẫn dùng duy nhất request `begin` và temp file được xóa.
- Response/error audit: raw upstream HTTP body không được gắn vào result; lỗi bất ngờ trả `operation failed`, validation payload được sanitize, domain `ValueError` chỉ phát thông báo kiểm soát. Agent unit đã có regression kiểm tra check code không xuất hiện trong result.
- Verification cập nhật: upload unit + agent upload selection `15 passed` (7 deselected); upload delivery-unknown route regression `3 passed`; Ruff, compileall và `git diff --check` đạt.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; chưa thực hiện network test với máy thật.
- Bước tiếp theo: audit response schema/bounds của status và file listing, nhất là danh sách file và telemetry provider trước khi đưa vào API/frontend; giữ nguyên giới hạn và không retry side-effect.

### 2026-10-21 — Phase 12: Connector status telemetry bounds

- Audit xác nhận file listing đã giới hạn 256 entry, chiều dài name/path, response HTTP tối đa 2 MiB và frame protocol tối đa 256 KiB. Status telemetry trước đó dùng `dict[str, Any]` chưa giới hạn field/value.
- `ConnectorPrinterStatusResult` giờ allowlist `state`, `filename`, `progress`, `temperatures`, `firmware_version`; giới hạn string 32/256/128 ký tự, tối đa 16 heater key, nhiệt trong `-300..1000°C`, progress hữu hạn trong `0..100`. Field lạ, chuỗi vượt giới hạn, NaN/Inf và số ngoài miền bị reject.
- FlashForge status parser chỉ nhận string cho state/filename/firmware, cắt độ dài, bỏ temperature ngoài miền và số không hữu hạn; không chuyển object firmware tùy ý thành string telemetry.
- Verification: provider verification + Connector agent unit `27 passed`; typed Connector status RPC integration `1 passed`; printer status route integration `1 passed`; file-list unit `3 passed`; Ruff đạt. Pydantic protected-namespace warnings hiện hữu.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; không có firmware capture hoặc máy thật. Status bounds bảo vệ wire/API contract, không thay physical smoke.
- Bước tiếp theo: physical smoke AD5M/Creator 5/Pro khi có phần cứng; nếu chưa có, rà lifecycle camera relay và contract tool-map sliced-owned. Không đánh dấu Phase 12 hoàn tất.

### 2026-10-21 — Phase 12: Creator 5 tool-map contract audit

- Đọc trực tiếp `src/creator5-api.js` và `test/flashforge-creator5-adapter.test.js` tại upstream commit `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`.
- Contract upstream của `materialMappings` là danh sách `{toolId, slotId, materialName, toolMaterialColor, slotMaterialColor}`. `toolId` là chỉ số zero-based logical tool; `slotId` là chỉ số one-based Creator 5 material slot. Upstream test xác nhận `toolMap: {0: 2, 1: 0}` tạo `toolId=0, slotId=3` và `toolId=1, slotId=1`.
- Upstream adapter chỉ tạo mapping khi caller cung cấp `toolMap`, `usedLogicalTools`, `logicalTools`; đối chiếu physical slot metadata từ `/detail`; chỉ gửi `materialMappings` nếu có hơn một mapping. Nó không tự suy ra mapping từ `slot_id` của slicer.
- Printbuddy hiện trích xuất `slot_id`, material/color/usage từ `slice_info.config`, và `_creator5_tool_count_from_file()` chỉ dùng số slot duy nhất để cấu hình `gcodeToolCnt`. `extract_nozzle_mapping_from_3mf()` phục vụ Bambu dual-nozzle, không chứng minh quan hệ Creator 5 logical tool → material slot. Hàng đợi hiện chỉ có `ams_mapping` với semantics Bambu và chặn nó cho Creator 5.
- Quyết định: tiếp tục từ chối mapping không tương thích; chưa gửi `materialMappings` hay suy diễn `toolId` từ `slot_id`. Connector path cũng chưa có trường/RPC cho mapping. Giữ capability mapping ở unavailable cho tới khi có metadata slicer cụ thể và đường truyền dữ liệu được kiểm chứng.
- Verification: audit mã nguồn upstream + unit tests upstream; không có thay đổi runtime code nên không chạy test suite trong checkpoint này.
- Evidence vẫn `source_inferred`, `hardware_verified=false`; upstream test chứng minh behavior của controller tham chiếu, không xác nhận firmware FlashForge.
- Bước tiếp theo: thiết kế contract riêng cho Printbuddy-owned Creator 5 jobs: parser chỉ đọc slicer metadata có thể chứng minh logical tool IDs; model/queue persistence tách biệt khỏi `ams_mapping`; direct start serialize exact upstream shape, validate đủ mappings/slot range và đọc status trước/sau. Sau đó thêm tests cho round-trip queue, incomplete/duplicate/out-of-range metadata, rồi mới xem xét Connector RPC. Printer-local files tiếp tục dùng mapping đã lưu trên máy.

### 2026-10-22 — Creator 5 explicit queue mapping contract

- Thêm trường riêng `creator5_material_mappings` vào queue model/schema/response, migration DB và TypeScript API client; không tái sử dụng `ams_mapping`. Mỗi entry dùng upstream field names `toolId` (0-3), `slotId` (1-4), `materialName`, `toolMaterialColor`, `slotMaterialColor`.
- Queue API chỉ nhận mapping khi job gắn với một máy `flashforge_creator5`; từ chối Bambu AMS mapping đi kèm. Update route giữ cùng ràng buộc khi đổi printer hoặc giữ mapping cũ.
- Scheduler xác thực mapping từ DB trước upload; sai JSON/shape/range/duplicate tool ID làm queue job fail closed. `PrinterManager` chuyển contract tới Creator 5 provider; `/printGcode` gửi `materialMappings` cùng start options và giữ status/file precheck + readback. Không có Connector RPC nên queue mapping không dùng qua Connector; Connector start tiếp tục từ chối mapping.
- Creator 5 file-local start không nhận mapping. Không sinh map tự động từ `slice_info.config`: `slot_id` hiện có không chứng minh logical `toolId`, và chưa có UI tạo map. API/queue contract hiện cho caller explicit mapping để Printbuddy-owned jobs; vẫn cần ràng buộc completeness với tool IDs thực sự được G-code dùng trước khi bật UI/tự động hóa.
- Thêm unit test cho exact upstream payload, malformed/single/duplicate/out-of-range map, queue schema và loại trừ AMS semantics.
- Verification: pytest chọn lọc với `--noconftest` `47 passed`; Ruff, compileall, TypeScript `tsc --noEmit` và `git diff --check` đạt. Chạy pytest thường bị môi trường chặn khi import fixture vì package `pyftpdlib.handlers` hiện tại không cung cấp `TLS_FTPHandler`.
- Hạn chế: tests dùng fake HTTP/schema, chưa xác minh firmware Creator 5; không có slicer fixture chứng minh logical tool IDs, không có UI hoặc Connector path. `source_inferred`, `hardware_verified=false`.
- Bước tiếp theo: lấy 3MF/G-code do Creator 5 slicer tạo để xác minh parser logical tool IDs và used-tool set; sau đó xây UI chỉ cho Printbuddy-owned queue, kiểm tra map đủ/chính xác với used tools, rồi thêm queue create/update persistence integration tests. Không bật Connector mapping cho tới khi RPC riêng được thiết kế.

### 2026-10-22 — Creator 5 parser và completeness gate cho queue mapping

- Thêm `flashforge/creator5_tool_requirements.py`: quét lệnh `T<n>` ngoài comment, metadata filament usage dương, và chỉ fallback về tool 0 khi metadata chỉ ra duy nhất một tool. Tool IDs ngoài miền 0-3, metadata multi-tool mơ hồ hoặc thiếu bằng chứng đều fail closed.
- Với 3MF, parser đọc `Metadata/plate_<plate_id>.gcode` theo `plate_id` 1-based của Printbuddy; archive nhiều plate bắt buộc chọn plate cụ thể. G-code nhúng bị giới hạn 16 MiB, file G-code rời 64 MiB và ZIP tối đa 10.000 entry.
- Scheduler xác thực mapping trước upload: tập `toolId` phải bằng chính xác tập logical tool parser trích được. Mapping thừa/thiếu, file hỏng, plate không tìm thấy hoặc usage mơ hồ không được gửi lên máy.
- Tool IDs là hợp của lệnh `T<n>` và các index có filament usage dương; chỉ fallback về metadata palette khi không có bằng chứng usage.
- Thêm test T0/T1, lọc comment, metadata usage, union hai nguồn bằng chứng, fallback single-tool, out-of-range, ambiguous/missing metadata, plate selection, ZIP payload quá lớn và exact mapping completeness.
- Verification: `pytest --noconftest` cho parser + queue mapping schema + Creator 5 provider `51 passed`; Ruff, compileall và `git diff --check` đạt.
- Giới hạn: fixtures ZIP/G-code tổng hợp, chưa có 3MF thực từ slicer Creator 5 hoặc firmware capture; Connector mapping/UI chưa có. Evidence `source_inferred`, `hardware_verified=false`.
- Bước tiếp: kiểm tra bằng file Creator 5/Orca/FlashPrint thực tế để xác nhận tên entry/metadata; sau đó thêm UI mapping chỉ cho Printbuddy-owned queue và persistence integration tests. Connector vẫn unavailable tới khi RPC contract riêng được thiết kế.

### 2026-10-22 — Creator 5 queue mapping UI submit guard

- Đã nối editor mapping Creator 5 vào PrintModal cho Printbuddy-owned queue; queue mapping chỉ được dùng khi chọn một máy Creator 5 và một plate cho file multi-plate.
- Guard chung `creator5MappingReady` hiện được dùng cả khi tính `canSubmit` lẫn trong `handleSubmit`, nên sự kiện submit từ form/Enter cũng không thể gửi mapping thiếu khi nút đang bị disable. Với multi-tool, yêu cầu một máy duy nhất và mapping khớp toàn bộ logical tools cùng các slot đang khả dụng; khi metadata đang tải hoặc có nhiều plate được chọn thì fail closed.
- Không đổi hành vi reprint/file-local; các luồng đó vẫn không thể tạo mapping bằng cách này. Giữ nguyên bằng chứng `source_inferred`, `hardware_verified=false`.
- Verification: backend parser/schema/provider/scheduler selected tests `62 passed`; Ruff, TypeScript `tsc --noEmit`, `git diff --check`, Creator 5 mapping component `2 passed`, i18n parity và production build đều đạt. Full Vitest có `631 passed, 11 failed`; các lỗi được thấy ở test cũ so khớp chuỗi tiếng Anh khi môi trường dùng locale vi, còn Creator 5 mapping component test pass. Build cảnh báo Node `20.12.2` dưới yêu cầu khuyến nghị của Vite và JS chunk >3 MiB.
- Còn thiếu fixture 3MF/G-code thật từ Creator 5/Orca/FlashPrint. Connector mapping vẫn unavailable; physical smoke chưa làm.
- Bước tiếp theo: thêm integration round-trip queue mapping và xác minh parser trên file slicer thật trước khi tuyên bố Creator 5 queue mapping hoàn chỉnh.

### 2026-10-22 — Creator 5 queue mapping API persistence

- Thêm integration coverage cho create/update/read/clear của `creator5_material_mappings`, gồm so sánh response API và JSON thực lưu trong DB. Kiểm tra thêm việc create với provider khác và chuyển queue item đang có mapping sang provider khác đều bị từ chối.
- Round-trip test phát hiện PATCH gọi `model_dump()` trên dict do `PrintQueueItemUpdate.model_dump()` tạo ra, gây HTTP 503. Sửa route serialize từ các `Creator5MaterialMapping` đã validate trên request model; response, DB và GET sau update đều giữ đúng mapping.
- Verification: queue API integration filter + queue mapping schema `3 passed`; Ruff, compileall và `git diff --check` đạt. Pydantic protected-namespace warnings hiện hữu.
- Rà workspace không thấy `.3mf`, `.gcode`, `.gx` hoặc `.bgcode` mẫu. Do đó parser mới chỉ được kiểm tra bằng fixture tổng hợp; firmware và máy thật vẫn chưa xác minh (`source_inferred`, `hardware_verified=false`).
- Bước tiếp theo: dùng file slicer Creator 5/Orca/FlashPrint để đối chiếu entry plate, lệnh `T<n>` và metadata filament usage; sau đó thực hiện physical smoke. Connector mapping vẫn unavailable.

## Quy tắc kết thúc MVP

MVP chỉ được gọi là hoàn tất khi ít nhất một họ máy đã đi hết direct path (verify, status, file, upload/start, job control, safety, diagnostics, tests) và có physical smoke evidence. Creator 5/Pro và Connector có thể phát hành sau theo feature flag nếu chưa đủ hardware evidence, nhưng phải giữ capability/error rõ ràng và cập nhật trạng thái trong bảng phase này.
