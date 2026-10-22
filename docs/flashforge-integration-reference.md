# Tài liệu tham chiếu tích hợp FlashForge cho Printbuddy

> Mục đích: cung cấp ngữ cảnh kỹ thuật cho AI/kỹ sư khi thiết kế hoặc nâng cấp hỗ trợ máy in FlashForge trong Printbuddy. Đây là ghi chú nghiên cứu giao thức từ mã nguồn bên ngoài, không phải xác nhận tương thích với firmware/phần cứng thực tế.

## Trạng thái và nguồn tham khảo

- Repository đã đọc: [Andy-Knight/Print-Farm-Controller](https://github.com/Andy-Knight/Print-Farm-Controller)
- Commit tham chiếu: `7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5`, tag `v0.59.0` (đọc ngày 2026-10-20).
- Rà soát material allowlist và `setCreator5FilamentConfig()` trực tiếp trong `src/creator5-api.js` tại commit này ngày 2026-10-21.
- Rà soát bổ sung semantics filtration trực tiếp tại commit này ngày 2026-10-21; chưa có firmware/readback evidence mới.
- Hệ thống tham chiếu triển khai bằng JavaScript/Node.js. Không thể nhập trực tiếp adapter vào backend Python của Printbuddy; chỉ dùng làm đặc tả giao thức/behavior, tự triển khai và kiểm chứng trong provider Python.
- Các đường dẫn dưới đây là đường dẫn trong repository tham chiếu ở commit trên; dùng URL GitHub gắn commit để tránh nội dung branch thay đổi.
- Creator 5/Creator 5 Pro có cảnh báo chưa hoàn tất xác thực trên máy thật theo tài liệu của dự án tham chiếu. Các payload cụ thể vẫn cần đối chiếu firmware thực tế.

## Tóm tắt cho AI

FlashForge không nên được xem như một giao thức duy nhất. Cần tách theo họ model:

| Họ máy | Kết nối | Xác thực | Ghi chú |
| --- | --- | --- | --- |
| Adventurer 5M / 5M Pro (AD5M) | HTTP `8898`, TCP `8899`, camera `8080` | `serialNumber` + `checkCode` cho HTTP | TCP dùng lệnh M-code cho file; HTTP `/gcodeList` chỉ là danh sách gần đây |
| Creator 5 / Creator 5 Pro | HTTP `8898`, camera `8080`; không dùng TCP `8899` | `serialNumber` + `checkCode` cho HTTP | Bốn đầu in/khe vật liệu; danh sách file HTTP gần đây; Pro có chamber API riêng |

Các cổng là mặc định của máy thật, không phải bảo đảm cho emulator/proxy. Không suy ra model chỉ từ port.

## Giao thức AD5M

Nguồn chính:

- [printer-api.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/printer-api.js)
- [tcp-files.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/tcp-files.js)
- [upload-gcode.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/upload-gcode.js)
- [flashforge-ad5m-adapter.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/adapters/flashforge-ad5m-adapter.js)

### HTTP API

Base URL: `http://{host}:8898`. JSON POST body thường bao gồm:

```json
{
  "serialNumber": "<serial>",
  "checkCode": "<LAN check code>"
}
```

Các endpoint được nguồn tham chiếu dùng:

| Endpoint | Hành vi |
| --- | --- |
| `POST /detail` | Trạng thái, tiến độ, nhiệt độ, tên file, firmware và metadata được firmware báo |
| `POST /gcodeList` | Danh sách file gần đây; firmware AD5M có thể chỉ trả tối đa 10 file gần nhất |
| `POST /control` | Lệnh có dạng `{"payload":{"cmd":"...","args":{...}}}` |
| `POST /printGcode` | Bắt đầu file đã có trên máy |
| `POST /uploadGcode` | Multipart upload, field file `gcodeFile`; header gồm `serialNumber`, `checkCode`, `fileSize`, `printNow=false`, `levelingBeforePrint` |

Các command quan sát trong mã nguồn gồm `temperatureCtl_cmd`, `printerCtl_cmd`, `circulateCtl_cmd`, `jobCtl_cmd`, `calibration_cmd`, `streamCtrl_cmd`. Mẫu đối số ở nguồn:

- Nhiệt: `rightNozzle`, `platform`; giới hạn adapter ghi nhận nozzle tối đa 265 °C, bed tối đa 110 °C.
- Quạt: `coolingFan`, `chamberFan`.
- Lọc khí: `internal`/`external` với giá trị `open` hoặc `close`.
- Job: `jobCtl_cmd` với `{jobID:"", action:"pause" | "continue" | "cancel"}`.
- Level bed: `calibration_cmd` với `{levelingDetection:"open", vibrationCompensation:"close"}`.
- Camera: yêu cầu `streamCtrl_cmd` `{action:"open"}`, sau đó URL MJPEG fallback `http://{host}:8080/?action=stream`.

Trong commit tham chiếu, `setFiltration()` chỉ chuyển boolean thành `open`/`close`, gửi `circulateCtl_cmd`, rồi trả kết quả command. `getStatus()` chỉ chuẩn hóa dữ liệu `/detail` và không đọc trạng thái `internal`/`external`; vì vậy ACK chỉ xác nhận API nhận lệnh, không chứng minh bộ lọc đã đổi trạng thái. Giữ capability này ở `planned` cho tới khi có firmware readback/state evidence và policy an toàn rõ ràng.

`openCamera()` gửi `streamCtrl_cmd {action:"open"}`, đọc lại `/detail.cameraStreamUrl`, rồi fallback sang `http://{host}:8080/?action=stream`. Commit này không cung cấp method/payload đóng camera; Printbuddy chỉ teardown proxy/upstream khi viewer rời, không gửi lệnh firmware close.

Rà soát semantics ngày 2026-10-21: `calibration_cmd` trong nguồn tham chiếu là calibration bed-leveling độc lập. Đây khác với cờ `levelingBeforePrint` khi gọi `/printGcode`. Printbuddy chỉ đánh dấu luồng trước print là implemented; endpoint calibration độc lập giữ `planned` vì `/detail` hiện chưa có readback chứng minh calibration bắt đầu/hoàn tất hoặc reconcile được sau timeout.

HTTP client tham chiếu có timeout, chỉ chấp nhận HTTP 2xx và JSON `code === 0`. Code khác 0 phải được coi là lỗi, kể cả code âm/dương. Code `-2` hoặc thông báo `LAN mode error` được diễn giải thành LAN API chưa bật. Hướng dẫn trên máy là bật LAN Only / Local Network Only.

### TCP file API

Base TCP port mặc định `8899`. Lấy danh sách file đầy đủ theo trình tự ngắn hạn:

1. Kết nối TCP, bật `TCP_NODELAY`.
2. Gửi `~M601 S1\n` để xin quyền điều khiển; từ chối nếu phản hồi báo control busy/failure.
3. Gửi `~M661\n` để nhận danh sách file. Firmware có thể gửi ACK rồi gửi payload thành nhiều đợt, do đó implementation đợi khoảng lặng trong stream (tham chiếu settle 1400 ms) và vẫn chấp nhận payload hữu ích không có `ok` chuẩn.
4. Trong `finally`, best-effort gửi `~M602\n` để nhả quyền, đóng socket dù thao tác lỗi.

Parser hỗ trợ payload delimiter `::` với đường dẫn `/data/...` và dạng legacy có `info_list.size`/tên file theo dòng. Lọc extension `.gcode`, `.gx`, `.g`, `.3mf`, bỏ prefix đường dẫn storage, chống trùng. Đây là giao thức độc quyền được suy ra từ implementation; cần test với từng firmware, và tuyệt đối không giữ control lock lâu hơn cần thiết.

Luồng file adapter ưu tiên M661 để có full listing, sau đó overlay thứ tự gần đây từ `/gcodeList`. Nếu TCP lỗi/bị chặn/busy, fallback HTTP và báo rõ danh sách không đầy đủ.

## Giao thức Creator 5 / Creator 5 Pro

Nguồn chính:

- [creator5-api.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/creator5-api.js)
- [flashforge-creator5-adapter.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/adapters/flashforge-creator5-adapter.js)
- [flashforge-creator5-adapter.test.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/test/flashforge-creator5-adapter.test.js)

Creator 5 dùng cùng HTTP API hiện đại tại `8898`, nhưng adapter tham chiếu bỏ TCP `8899`. Không tái sử dụng các giả định một toolhead/file listing của AD5M. `/detail` được chuẩn hóa thành bốn tool (`T0`–`T3`), bốn nhiệt nozzle và bốn slot vật liệu. `currentSlot` là slot vật liệu đang cấp, không nhất thiết là tool đang hoạt động. Nguồn dùng duy nhất một nozzle target khác 0 như gợi ý active tool; nếu mơ hồ thì để active tool unknown.

Điều khiển Creator 5 trong mã tham chiếu:

- Vật liệu: `msConfig_cmd`, args `{slot: toolIndex + 1, mt: material, rgb: color}`. Chỉ cho thay đổi khi idle; sau lệnh đọc lại trạng thái tối đa 3 lần để xác minh. Material allowlist: `PLA`, `PETG`, `PLA-CF`, `PETG-CF`, `ABS`, `ASA`, `SILK`, `PET-CF`, `PAHT-CF`, `S-PAHT`, `S-Multi`, `PA-CF`, `HIPS`, `PVA`, `TPU-90A`, `TPU-95A`, `TPU-64D`, `PC`, `PA`, `PC-ABS`, `PPS-CF`. Color allowlist là 24 giá trị hex: `#FFFFFF`, `#FFF245`, `#DEF578`, `#21CC3D`, `#167A4B`, `#156682`, `#24E4A0`, `#7BD9F0`, `#4CAAF8`, `#2E54DD`, `#48358C`, `#A341F7`, `#F435F6`, `#D5B4DE`, `#FA6173`, `#F82D29`, `#805003`, `#F9903B`, `#FCEBD7`, `#D5C5A1`, `#B17C38`, `#8C8C89`, `#BEBEBE`, `#1B1B1B`. Khi chỉ đổi một trường, adapter tham chiếu giữ nguyên giá trị trường còn lại từ status hiện tại; thiếu giá trị hiện tại thì từ chối thay đổi.
- Nhiệt độ: `temperatureCtl_cmd`, args có `nozzles` là mảng bốn phần tử dùng `-200` cho tool không đổi, `platform` cho bed. Giới hạn nozzle 320 °C, bed 120 °C.
- Creator 5 Pro: có thể có `chamber` đến 65 °C. Creator 5 thường không được gán sensor/control chamber.
- Job: `jobCtl_cmd`, `{jobID:"", action:"pause" | "continue" | "cancel"}`.
- Level: `calibration_cmd`, `{levelingDetection:"open", vibrationCompensation:"close"}`.
- Print: `POST /printGcode`; tùy chọn gồm `fileName`, `levelingBeforePrint`, `flowCalibration`, `timeLapseVideo`, và `materialMappings` khi cần mapping multi-tool.
- Upload: `/uploadGcode` multipart (`gcodeFile`); Creator 5 thêm headers `useMatlStation=true`, `gcodeToolCnt` (1-4), `flowCalibration`, `timeLapseVideo`. Upload không tự in (`printNow=false`), nên start là thao tác riêng. Adapter tham chiếu dùng HTTP timeout đến 5 phút và `Expect: 100-continue` với fallback gửi body sau timeout chờ; Printbuddy hiện tách upload timeout 300 giây, còn Expect handshake/fallback là việc Phase 8.
- Start Creator 5: trước command, adapter tham chiếu chỉ cho idle và xác minh filename có trong HTTP recent list; sau `/printGcode`, Printbuddy cũng cần reconcile `/detail` tới RUNNING cùng filename. Recent list không đầy đủ và không có size nên không chứng minh upload integrity.
- Job Creator 5 dùng `jobCtl_cmd` với `{jobID:"", action:"pause" | "continue" | "cancel"}`. Reference chỉ trả command response; Printbuddy phải kiểm tra state trước và đọc lại state sau, không coi ACK là hoàn tất.
- Camera: mã tham chiếu thử lần lượt `streamCtrl` và `streamCtrl_cmd` với `{action:"open"}`, rồi MJPEG tại `http://{host}:8080/?action=stream`.

File browser chỉ dùng `/gcodeList` (nguồn báo gần đây, không đầy đủ). Firmware không cung cấp requirements tool/material cho file local đã nằm trên máy. Chỉ Printbuddy-owned sliced file metadata có thể được tin cậy để mapping tự động. Không tự đoán requirements cho file local.

## FlashForge discovery

Nguồn: [discovery.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/discovery.js), [discovery-network.js](https://github.com/Andy-Knight/Print-Farm-Controller/blob/7c1687e4c7e356d30b2cf9e1b88770a5f314b6e5/src/discovery-network.js).

- UDP multicast `225.0.0.9` và broadcast (`255.255.255.255`, directed broadcast theo network interface) trên các port `8899`, `19000`, `48899`.
- Có thể gửi thêm tới các host trong subnet cấu hình giới hạn `/22`–`/30`; subnet rộng bị từ chối để tránh scan không giới hạn.
- Response mới dài 276 bytes: parse name, commandPort, vendor/product ID, status, productType, eventPort, LAN mode và serial. PID map trong mã nguồn: `0x0023` AD5M, `0x0024` AD5M Pro, `0x0026` AD5X, `0x0028` Creator 5, `0x0029` Creator 5 Pro.
- Creator 5 discovery đôi khi quảng bá command port; adapter vẫn cố ý không dùng TCP 8899.
- Với subnet cấu hình, có fallback TCP probe port 8899, gửi `~M115\n`; xác nhận bằng `Machine Type`, `SN`, và `FlashForge`, rồi chỉ nhận AD5M family theo logic hiện tại.
- Discovery chỉ cung cấp endpoint/identity sơ bộ. Cần bước credential verification riêng trước khi lưu hoặc điều khiển.

## Ánh xạ vào kiến trúc Printbuddy hiện tại

Đọc codebase hiện tại trước khi sửa vì các thay đổi đang dở có thể thay đổi vị trí/hợp đồng:

- Provider registry: `backend/app/services/printer_providers/factory.py` (`SUPPORTED_PROVIDERS`, `create_printer_client`).
- Provider contract: `backend/app/services/printer_providers/base.py` (`PrinterClientProtocol`).
- Printer fields: `backend/app/models/printer.py`; schema/provider literal/defaults: `backend/app/schemas/printer.py`.
- Lifecycle/status: `backend/app/services/printer_manager.py`.
- Add/test printer and file/control APIs: `backend/app/api/routes/printers.py`.
- Upload/queue: `backend/app/services/background_dispatch.py`, `backend/app/services/print_scheduler.py`, `backend/app/api/routes/print_queue.py`, `backend/app/api/routes/library.py`.
- Connection routing abstraction: `backend/app/services/printer_transport.py`; connector wire messages: `connector_protocol/__init__.py`, agent: `connector/printbuddy_connector.py`.
- Discovery API/service: `backend/app/services/discovery.py`, `backend/app/api/routes/discovery.py`.
- Camera: `backend/app/services/camera.py`, `backend/app/api/routes/camera.py`, cùng external camera helpers.

> **Lưu ý về trạng thái hiện tại:** inventory ngày 2026-10-20 thấy provider factory/schema chưa đăng ký FlashForge. Connector hiện hỗ trợ discovery, verify và TCP reachability status; protocol chưa có RPC control/status telemetry/file/camera đầy đủ. Kiểm tra lại branch trước khi dựa vào nhận định này.

### Hướng triển khai đề xuất

1. Tạo một hoặc nhiều provider FlashForge riêng cho `flashforge_ad5m` và `flashforge_creator5`, hoặc một provider hãng với capability/model policy phân nhánh. Ưu tiên thiết kế khiến TCP 8899 không xuất hiện như capability cho Creator 5.
2. Chuẩn hóa trạng thái sang `PrinterInfo`/state Printbuddy. Giữ null/unknown khi firmware không cung cấp; không tạo dữ liệu filament/nozzle/presence giả.
3. Dùng async-native HTTP/TCP clients hoặc `asyncio.to_thread` đúng theo kiến trúc hiện tại; đặt timeout/cancellation cho mọi socket và upload lớn. Không chặn event loop.
4. Tích hợp lần lượt verify/connect, status, print controls, file list/upload/start/delete, camera và discovery; gate API/UI bằng capability thay vì giả định mọi provider hỗ trợ Bambu features.
5. Lưu ports/model-specific options trong `provider_options` có schema validation; không nhét checkCode vào frontend public state. Hiện `access_code` có thể dùng làm nơi chứa secret nhưng cần xác minh mapping hiện tại và tránh vô tình trả secret qua `PrinterResponse`.
6. Nếu dùng Connector, thêm message types/request-response cho các thao tác thật, giới hạn provider/operation/host/port, kiểm tra quyền ở server, timeout và giới hạn dữ liệu. Không dùng status reachability probe hiện có như thể đó là điều khiển printer.
7. Đưa discovery vào Connector khi server không cùng LAN. Giữ giới hạn subnet/host/concurrency, lọc kết quả và yêu cầu user chọn endpoint; discovery không tự thêm máy.

## Bảo mật và độ tin cậy

- Check code là credential có quyền điều khiển. Mã hóa khi lưu theo cơ chế secrets hiện có; che khỏi response, audit log, exception, telemetry và Connector logs.
- Giao thức HTTP/camera URL trong nguồn tham chiếu là HTTP không TLS. Chỉ dùng trên LAN/VPN tin cậy; không expose thẳng ra Internet. Khi qua Connector, chỉ relay lệnh có cấu trúc, không tạo tunnel tùy ý.
- Validate host/port ở server và Connector để hạn chế SSRF. Chỉ cho port mặc định/cấu hình cho phép; không follow redirect ngoài host dự kiến; giới hạn response size và thời gian.
- Không retry lệnh có tác dụng phụ mù quáng (print, cancel, upload, config). Sau timeout có thể lệnh đã tới máy; reconcile bằng status/file listing trước khi quyết định thử lại.
- Tách ACK tiếp nhận lệnh khỏi xác nhận trạng thái thực. Sau upload kiểm tra file tồn tại nếu giao thức hỗ trợ; sau print start poll/verify trạng thái và filename.
- TCP M601/M602 có control lock toàn máy: serialize thao tác TCP cùng printer, release trong `finally`, và báo busy thay vì tranh quyền vô hạn.
- Camera MJPEG cần auth/proxy phù hợp với chính sách camera Printbuddy; tránh nhúng credential vào URL/log. Camera endpoint trên máy tham chiếu có vẻ không authenticated.
- Một số lệnh Creator 5 có thể trả `Success` dù firmware không áp dụng. Đọc lại state khi có thể; capability theo model không thay cho validation phần cứng.

## Kiểm thử tối thiểu trước khi phát hành

- Unit tests parser `/detail`, map trạng thái/progress/tool/slot, normalize file paths, M661 formats, discovery packet và PID/model.
- Fake HTTP server kiểm tra credentials/body, HTTP/code errors, LAN mode error, timeout, malformed JSON, payload/response size.
- Fake TCP server kiểm tra acquire → M661 payload nhiều chunk → release; busy; disconnect; timeout; cancellation; filename có dấu cách/Unicode; không rò control lock.
- Upload multipart test với file lớn/stream, Expect: 100-continue và printer không hỗ trợ Expect; xác nhận upload không tự start.
- Test từng thao tác có side effect với ACK lỗi/timeout và readback reconciliation.
- Provider factory/schema/add-printer tests; lifecycle status; routes; queue/background dispatch; feature gates; secret scrubbing.
- Connector tests đảm bảo request type, timeout, giới hạn target và authorization cho từng thao tác; offline phải fail rõ ràng.
- Emulator protocol là nguồn test hữu ích nhưng không chứng minh firmware tương thích. Cần smoke test vật lý có giám sát cho từng model/firmware: verify, status, file list, upload file nhỏ, print/start/pause/cancel, nhiệt, camera.

## Giới hạn và câu hỏi mở

- Mã tham chiếu không phải tài liệu API chính thức của FlashForge. Tên command, payload, PID, parser và firmware quirks cần xác thực bằng captures/docs đáng tin cậy hoặc máy thật.
- Creator 5 / Pro hardware validation chưa hoàn tất theo dự án tham chiếu.
- Nguồn tham chiếu không làm rõ auth/ACL riêng cho TCP 8899, bảo đảm atomicity upload, semantics đầy đủ của response, hay tính ổn định của endpoint camera qua firmware.
- Mức nhiệt/feature capability có thể đổi theo model/firmware. AD5M 265/110 °C và Creator 5 320/120 °C là giá trị trong adapter tham chiếu, không nên áp dụng không điều kiện.
- Xác định rõ scope ban đầu Printbuddy cần AD5M, Creator 5 hay cả hai; không để yêu cầu một model làm phát sinh capability khai báo cho model còn lại.

## Quy tắc cho phiên AI tiếp theo

- Đọc file này cùng `MEMORY.md`, `docs/printbuddy-system-memory.md`, provider factory/base, schema/model, printer manager, routes, dispatch/scheduler, connector và tests hiện tại trước khi code.
- Xem tài liệu này là input tham khảo, không phải yêu cầu triển khai đầy đủ hay đặc tả chuẩn FlashForge.
- Trước khi thêm provider, vẽ luồng cả direct và connector; tìm mọi nhánh Bambu-specific trong file listing/upload/print/camera/queue thay vì chỉ làm status hiển thị.
- Cập nhật tài liệu sau khi có kết quả capture hoặc thử nghiệm máy thật; ghi model, firmware, command, response đã xác nhận và ngày kiểm thử.
- Không chỉnh sửa/ghi đè các thay đổi đang có trong working tree khi tiếp tục công việc.
