# Kế hoạch triển khai Printbuddy Connector

Ngày lập: 2026-10-15  
Trạng thái: Đề xuất để làm cơ sở triển khai  
Phạm vi: Kết nối máy in nằm trong mạng riêng của người dùng với Printbuddy Server ở mạng khác

## 1. Mục tiêu

Printbuddy Connector là chương trình chạy trong mạng nội bộ có máy in. Connector chủ động kết nối outbound tới Printbuddy Server qua TLS trên cổng 443, sau đó chuyển tiếp trạng thái, lệnh, file và camera theo quyền được cấp. Router tại nhà người dùng không cần mở cổng inbound và server không cần gọi trực tiếp IP LAN của máy in.

Mục tiêu sản phẩm:

- Người dùng đăng ký một Connector với Printbuddy bằng mã ghép nối có thời hạn.
- Một Connector quản lý được nhiều máy in trong một mạng.
- Người dùng có thể quét, thêm, theo dõi, điều khiển và gửi file tới các máy in được Connector quản lý.
- Connector offline không làm hỏng dữ liệu máy in; giao diện thể hiện rõ trạng thái mất kết nối.
- Máy in đang kết nối trực tiếp tiếp tục hoạt động theo luồng hiện tại.
- Quyền truy cập Connector, máy in, file và camera được kiểm tra ở server trước mỗi thao tác.

Ngoài phạm vi giai đoạn đầu: truy cập mạng nội bộ tổng quát, shell từ xa, tunnel TCP tùy ý, cập nhật firmware không có xác nhận, và thay thế các API Bambu Cloud.

## 2. Kiến trúc đích

```text
Browser
  │ HTTP /api/v1 và WebSocket người dùng
  ▼
Printbuddy Server
  ├─ API, quyền truy cập, cơ sở dữ liệu, hàng đợi lệnh
  ├─ Connector Gateway: xác thực và quản lý phiên agent
  └─ File staging: URL tải lên/tải xuống có hạn dùng
       ▲
       │ WSS outbound qua TLS/443, heartbeat, lệnh và sự kiện
       ▼
Printbuddy Connector (trong mạng của người dùng)
  ├─ discovery và kiểm tra kết nối LAN
  ├─ MQTT/TLS tới Bambu
  ├─ FTPS tới máy in khi truyền file
  ├─ camera theo yêu cầu
  └─ hàng đợi cục bộ ngắn hạn và nhật ký đã khử bí mật
       │
       └─ Máy in trong LAN
```

Kết nối giữa browser và Printbuddy hiện có `/api/v1/ws` dành cho sự kiện giao diện. Connector cần endpoint riêng, ví dụ `/api/v1/connectors/ws`, vì cơ chế xác thực, vòng đời, phân luồng và giới hạn tải khác với WebSocket của người dùng.

## 3. Căn cứ trong mã nguồn hiện tại

- `backend/app/models/printer.py`: máy in hiện lưu `ip_address`, `access_code`, provider và thông tin API.
- `backend/app/api/routes/printers.py`: tạo máy in gọi kiểm tra kết nối trước khi lưu.
- `backend/app/services/printer_manager.py`: quản lý client kết nối và trạng thái trong tiến trình ứng dụng.
- `backend/app/services/bambu_mqtt.py`: MQTT kết nối trực tiếp `ip_address:8883`.
- `backend/app/services/bambu_ftp.py`: FTPS kết nối trực tiếp `ip_address:990`.
- `backend/app/services/background_dispatch.py` và `backend/app/main.py`: còn các luồng upload, archive, timelapse hoặc tác vụ nền sử dụng IP/access code trực tiếp.
- `backend/app/api/routes/camera.py` cùng camera services: proxy/đọc luồng camera có phụ thuộc mạng.
- `backend/app/core/database.py`: migration schema nằm trong ứng dụng; không có Alembic history riêng.
- `backend/app/core/websocket.py` và `backend/app/api/routes/websocket.py`: WebSocket hiện tại broadcast trạng thái cho browser, không phải transport cho Connector.
- `backend/app/services/printer_providers/`: đã có provider boundary cho các hãng/protocol, nhưng chưa trừu tượng hóa cách định tuyến qua Connector.

Do đó, chỉ thêm cột `connector_id` vào bảng printer là chưa đủ. Các service cần được chuyển từ kết nối socket trực tiếp sang một giao diện transport có thể chọn direct hoặc connector.

## 4. Quyết định kiến trúc cần chốt trước khi viết code

### 4.1 Connector là tiến trình độc lập

Connector nên là chương trình riêng, đóng gói thành binary/service cho Windows và Linux, đồng thời có image Docker. Không nên yêu cầu người dùng cài toàn bộ ứng dụng Printbuddy trên máy trong LAN. Một tiến trình riêng giúp cập nhật độc lập, giới hạn credential và giảm phụ thuộc môi trường.

Có thể chọn Python cho bản đầu để tận dụng kiến thức và thư viện giao thức hiện có. Tuy nhiên không nên import trực tiếp `backend.app` từ connector đã phát hành: module server có nhiều phụ thuộc và vòng đời ứng dụng. Tách phần dùng chung thành thư viện nhỏ hoặc đóng gói giao thức/thông điệp độc lập để tránh buộc Connector cài cả backend.

### 4.2 Kết nối agent

- Connector mở WSS outbound tới hostname server do admin cấu hình.
- TLS certificate phải được xác thực bình thường; không bỏ qua kiểm tra hostname/chứng thư.
- Mỗi Connector có `connector_id`, credential dài hạn có thể thu hồi, và khóa riêng/certificate riêng.
- Credential được cấp sau quá trình enrollment; enrollment token chỉ dùng một lần, có thời hạn ngắn và scope tối thiểu.
- Reconnect dùng backoff có jitter; heartbeat báo phiên bản, thời điểm hoạt động và sức khỏe, không gửi secret.
- Mọi thông điệp có `message_id`, `connector_id`, `sent_at`, `schema_version`, `type` và payload có giới hạn kích thước.
- Có giới hạn số phiên, số lệnh đồng thời, kích cỡ frame và tốc độ gửi theo Connector.

### 4.3 Lệnh và sự kiện

Lệnh điều khiển phải có ID duy nhất, printer ID, loại lệnh được allowlist, payload schema, deadline và idempotency key. Server ghi lệnh vào DB trước khi gửi. Connector trả trạng thái nhận lệnh, bắt đầu, hoàn tất hoặc thất bại. Server không tự phát lại lệnh nguy hiểm khi không rõ Connector đã thực thi hay chưa.

Các trạng thái đề xuất: `queued`, `sent`, `accepted`, `running`, `succeeded`, `failed`, `expired`, `cancelled`, `delivery_unknown`.

Các sự kiện telemetry có thể gộp/coalesce để trạng thái cũ không xếp hàng vô hạn. Lệnh điều khiển và kết quả lệnh phải được giữ bền; telemetry thường xuyên có thể loại bỏ khi quá tải rồi gửi snapshot mới nhất.

### 4.4 Chạy nhiều server instance

Trong bản triển khai một instance, gateway có thể giữ WebSocket trong bộ nhớ tiến trình. Nếu Printbuddy chạy nhiều worker/replica, phải có broker dùng chung (ví dụ Redis streams/pub-sub hoặc bảng hàng đợi trong DB với lease) để route lệnh đến đúng phiên Connector. Kế hoạch giai đoạn đầu nên tuyên bố hỗ trợ một app instance; thiết kế ID/lease không được ngăn việc bổ sung broker sau này.

## 5. Mô hình dữ liệu đề xuất

Tên bảng/field cuối cùng cần tuân theo quy ước model trong repo. Các field dưới đây là phạm vi logic.

### `connectors`

- `id`: ID nội bộ.
- `public_id`: ID ngẫu nhiên dùng trong giao thức, không phải khóa DB tuần tự.
- `owner_user_id`: chủ sở hữu.
- `name`: tên do người dùng đặt.
- `status`: `pending`, `online`, `offline`, `revoked`.
- `version`, `platform`, `last_seen_at`, `created_at`, `updated_at`.
- `public_key` hoặc hash certificate để xác thực Connector.
- `credential_hash`/key version; tuyệt đối không lưu token thô ở dạng đọc được.
- `revoked_at`, `last_disconnect_reason` đã lọc dữ liệu nhạy cảm.

### Printer và liên kết Connector

Thêm vào printer hoặc bảng liên kết riêng:

- `connection_mode`: `direct`, `vpn`, `connector`.
- `connector_id` khi mode là `connector`.
- Host/IP nội bộ chỉ được Connector sử dụng.
- `last_agent_status_at` hoặc trạng thái health được server tổng hợp.

Vì một máy in có thể được chuyển giữa Connector, direct và VPN, cần ghi rõ quy tắc thay đổi mode. Giai đoạn đầu giới hạn mỗi printer thuộc tối đa một Connector tại một thời điểm.

### `connector_enrollments`

- hash của token enrollment, connector owner dự kiến, thời hạn, trạng thái sử dụng và metadata tạo.
- Token chỉ dùng một lần và không ghi vào application log.

### `connector_commands`

- ID/idempotency key, connector, printer, loại lệnh, payload đã validate, trạng thái, thời điểm tạo/gửi/hoàn tất, mã lỗi chuẩn hóa.
- Không lưu access code, credential MQTT hoặc toàn bộ nội dung file trong payload.
- Có thời hạn lưu/cleanup theo cấu hình.

Nếu dùng bảng liên kết printer riêng, cần unique constraint để printer chỉ có một Connector active. Thêm FK/index phù hợp, `ON DELETE` được chọn rõ và migration chạy được trên SQLite lẫn PostgreSQL.

## 6. Quản lý credential và dữ liệu nhạy cảm

Mục tiêu là giảm dữ liệu nhạy cảm lưu ở server và luôn mã hóa nếu phải lưu.

- Access code Bambu nên được gửi mã hóa tới Connector và lưu trong kho cục bộ của hệ điều hành nếu có thể: Windows Credential Manager/DPAPI, Linux secret store hoặc file riêng với quyền hệ thống chặt.
- Khi server cần quản lý credential cho thao tác đăng ký lại, dùng encryption-at-rest dựa trên cơ chế mã hóa secret hiện có của dự án, key ở ngoài DB.
- Không gửi access code trong telemetry, error message, diagnostics hoặc log.
- Connector credential nên là token ngẫu nhiên có thể rotate/revoke, lưu hash phía server. Nếu dùng chữ ký public-key, server phát challenge ngắn hạn và Connector ký bằng private key.
- Enrollment token hiển thị một lần, TTL khuyến nghị 5-10 phút, dùng một lần, gắn với user và quyền enrollment.
- Tạo rate limit theo user/IP/token; giới hạn số Connector theo policy.
- Các endpoint gateway phải xác thực Connector trước khi parse/dispatch payload nặng.

## 7. Printer Transport trong backend

Thêm lớp abstraction dịch vụ, tên gợi ý `PrinterTransport`, với route trực tiếp hoặc Connector. API người dùng hiện có tiếp tục gọi domain service; domain service không tự mở socket bằng `printer.ip_address` nữa.

Các trách nhiệm tối thiểu:

- `test_connection(printer)`.
- `connect/disconnect` và subscribe trạng thái.
- `request_status`, `send_command`.
- `list_files`, `upload_file`, `download_file`, `delete_file`.
- `get_snapshot` và mở/đóng camera session.
- `diagnostic` với kết quả từng capability.

Không ép tất cả provider vào capability Bambu. Giao diện transport phối hợp với provider client/capability hiện có; Bambu AMS/FTP-specific calls phải tiếp tục được gate đúng cách.

Trong giai đoạn chuyển tiếp, direct transport sẽ gọi code hiện hành. Connector transport gửi RPC đã định kiểu. Có thể để một số tác vụ không được Connector hỗ trợ trả lỗi `capability_unavailable` rõ ràng, thay vì fallback âm thầm sang IP direct.

## 8. Luồng trải nghiệm người dùng

### Thêm Connector

1. Người dùng có quyền quản lý mở Settings → Connectors → Add.
2. Server trả mã/QR enrollment có TTL, ghi nhận user, thời hạn và trạng thái chưa dùng.
3. Người dùng tải bản cài tương ứng hoặc chạy image Docker, nhập URL server và mã.
4. Connector xác thực TLS, đổi mã lấy credential dài hạn, tạo/đăng ký khóa riêng.
5. Server hiển thị tên, phiên bản, nền tảng và online status.
6. Người dùng đặt tên/nhóm, kiểm tra kết nối và có thể revoke.

### Thêm máy in qua Connector

1. Người dùng chọn Connector đang online rồi yêu cầu quét subnet hoặc nhập hostname/IP nội bộ.
2. Server kiểm tra quyền và gửi discovery request qua Connector.
3. Connector quét trong LAN với giới hạn CIDR/port/timeouts; không nhận subnet đích tùy ý từ user không có quyền quản trị.
4. Server hiển thị kết quả; người dùng chọn máy in và nhập credential cần thiết.
5. Connector xác nhận MQTT/HTTP/API tương ứng; server lưu printer ở mode `connector`.
6. Gửi trạng thái thử nghiệm; giao diện báo kết quả MQTT, file transfer và camera riêng biệt.

### Máy in offline

- Connector offline: máy in vẫn tồn tại nhưng hiển thị “Connector offline”; disable lệnh mới hoặc cho phép người dùng xếp lệnh tùy policy.
- Không giả trạng thái máy in là disconnected do lỗi MQTT riêng nếu Connector chưa báo.
- Khi Connector online lại, lấy status snapshot trước, sau đó nối tiếp sự kiện mới; không phát lệnh hết hạn.
- Lệnh `start_print`, `stop`, firmware hoặc thao tác có hậu quả không được xếp hàng để chạy muộn nếu user chưa xác nhận policy.

## 9. Truyền file

Không truyền file lớn trong payload WebSocket.

### Server xuống máy in

1. Backend cấp URL object/file staging có TTL ngắn, giới hạn đúng file và một lần tải.
2. Server gửi lệnh metadata cho Connector.
3. Connector tải HTTPS dạng streaming, kiểm tra length/hash và giới hạn dung lượng.
4. Connector upload tới FTPS máy in trong LAN.
5. Connector trả kết quả, kích thước/hash và xóa file cache tạm sau TTL.

### Máy in lên server

1. Connector tải file từ máy in, stream tới endpoint upload staging đã được cấp quyền.
2. Server kiểm tra owner/printer, size, hash và nội dung theo các quy tắc upload hiện hữu.
3. Server đưa file vào archive/library qua service hiện có, không tạo đường ghi file tùy ý.

Upload cần hỗ trợ timeout, resume hoặc retry an toàn, giới hạn song song và cleanup khi Connector ngắt kết nối. Passive FTP có thể cần dải cổng/định tuyến phía LAN; lỗi này phải được báo riêng trong diagnostics.

## 10. Camera

Camera không nên mở một tunnel TCP tùy ý. Triển khai theo cấp độ:

1. Giai đoạn đầu chỉ hỗ trợ snapshot theo yêu cầu.
2. Live stream dùng session có TTL và token ngắn hạn, được gắn với user, printer, Connector và browser session.
3. Server kết thúc phiên khi tab đóng, token hết hạn hoặc quyền bị thu hồi.
4. Có giới hạn bitrate, thời lượng, số session và xử lý reconnect.

RTSP credentials/URL không được đưa ra frontend. Tránh buffer toàn bộ stream trong RAM; dùng relay theo chunk hoặc media proxy có giới hạn.

## 11. API và protocol dự kiến

Các tên dưới đây định hướng, không phải contract cuối cùng.

### API do browser gọi

- `POST /api/v1/connectors/enrollments`: tạo enrollment.
- `GET /api/v1/connectors`: liệt kê Connector mà user được phép thấy.
- `GET /api/v1/connectors/{id}`: thông tin và health.
- `POST /api/v1/connectors/{id}/revoke`: thu hồi.
- `POST /api/v1/connectors/{id}/discoveries`: yêu cầu quét/kiểm tra.
- `GET /api/v1/connectors/{id}/commands/{command_id}`: truy vấn tiến trình lệnh.

### Endpoint Connector

- `POST /api/v1/connectors/enroll`: đổi enrollment code lấy credential.
- `WSS /api/v1/connectors/ws`: phiên dài hạn xác thực Connector.
- `POST /api/v1/connectors/{public_id}/heartbeat` chỉ cần nếu thiết kế không gửi heartbeat trên WSS.
- Endpoint upload/download file riêng, token tạm thời và content length bắt buộc.

Không đưa token Connector vào query string vì URL có thể xuất hiện trong access log. Dùng header ban đầu hoặc auth frame sau khi TLS đã thiết lập, theo một handshake có chống replay.

## 12. Phân quyền và cô lập dữ liệu

- Connector thuộc một owner hoặc group theo mô hình phân quyền hiện có.
- Các user khác chỉ được sử dụng printer qua quyền được cấp, không tự động thấy cấu hình mạng/credential Connector.
- Quyền xem printer, điều khiển, file upload/download, camera và quản lý Connector là các hành động riêng.
- Kiểm tra permission ở API trước khi tạo command, và kiểm tra binding `printer -> connector` lần nữa trong dispatcher.
- Connector chỉ nhận lệnh cho những printer đã đăng ký với chính nó.
- Chặn replay lệnh cũ, command ID trùng, payload sai schema và printer ID không thuộc connector.
- Audit log tối thiểu gồm actor, user, connector, printer, action, kết quả, thời điểm; không ghi payload nhạy cảm.

## 13. Các giai đoạn triển khai

### Giai đoạn 0 — khảo sát và chốt contract

- Lập danh sách mọi call site trực tiếp tới `ip_address`/`access_code` trong printer, camera, file, queue, archive, firmware và background jobs.
- Đánh dấu capability dùng cho từng provider.
- Chốt phiên bản protocol, auth handshake, command envelope, TTL/file staging và policy khi Connector offline.
- Tạo threat model ngắn và quyết định credential lưu ở đâu.

Điều kiện hoàn tất: có inventory call site và contract được kiểm tra bằng schema/fixture.

### Giai đoạn 1 — quản lý Connector

- Thêm model, schema và migration idempotent SQLite/PostgreSQL.
- Enrollment token dùng một lần, TTL, revoke và ownership.
- Thêm permission và API/UI Settings để tạo, xem, đổi tên, thu hồi Connector.
- Tạo Connector prototype chỉ enroll, giữ WSS, heartbeat, báo version/health.
- Thêm metric/log có redaction.

Điều kiện hoàn tất: Connector có thể enroll, reconnect, hiện online/offline và bị revoke; không có chức năng điều khiển máy in.

### Giai đoạn 2 — discovery và transport nền

- Đóng gói Connector cho Windows/Linux/Docker.
- Thêm yêu cầu discovery qua Connector, kiểm tra subnet và port. Nền tảng hiện tại dùng request/response đồng bộ, chỉ cho private CIDR tối đa 256 host, tối đa 16 port, timeout giới hạn và trả tối đa 256 endpoint đã lọc; scanner chỉ TCP reachability, không nhận URL/banner/credential.
- Thêm printer `connection_mode=connector`, `connector_id`, migration/backfill `direct`.
- Thêm `PrinterTransport` và route direct giữ behavior hiện tại.
- Test add printer qua Connector bằng máy giả lập/protocol fixture.

Điều kiện hoàn tất: máy in có thể thêm qua Connector và diagnostic phản ánh chính xác MQTT/HTTP reachability.

### Giai đoạn 3 — status và điều khiển

- Connector giữ MQTT session cho Bambu và chuyển status snapshot/events về server.
- Chuyển lệnh start/pause/resume/stop và các lệnh Bambu cơ bản qua command queue.
- Tích hợp callback Printbuddy hiện có để archive, notification, queue và WebSocket người dùng tiếp tục hoạt động.
- Xử lý reconnect, trạng thái stale, sequence/version và mất event.

Điều kiện hoàn tất: trải nghiệm bảng điều khiển và print lifecycle hoạt động qua Connector; regression test chứng minh direct mode vẫn hoạt động.

### Giai đoạn 4 — file transfer

- Dùng staging URL một lần và streaming.
- Chuyển upload file và list/download/delete file sang Connector theo capability.
- Tích hợp `background_dispatch`, queue, archive và timelapse.
- Xử lý retry/idempotency, checksum, disk quota và cleanup.

Điều kiện hoàn tất: gửi file đến máy in Connector, nhận archive/timelapse về server; file lớn không đi qua RAM/WebSocket.

### Giai đoạn 5 — camera và capability nâng cao

- Snapshot trước, live stream sau.
- Chuyển diagnostics, AMS updates, firmware/advanced commands theo từng capability.
- Tạo UI hiển thị capability không được hỗ trợ thay vì làm hỏng toàn printer.

Điều kiện hoàn tất: từng capability có test, quyền riêng và timeout/cancel rõ ràng.

### Giai đoạn 6 — phát hành và vận hành

- Auto-update có chữ ký hoặc manifest tin cậy; rollback khi cập nhật lỗi.
- Version compatibility giữa server và Connector; hỗ trợ một số phiên bản gần nhất.
- Gói cài Windows service, systemd, Docker, hướng dẫn log/support.
- Giới hạn Connector theo plan nếu đây là chính sách sản phẩm.
- Pilot với một Connector/Linux Docker và một Connector/Windows trước khi mở rộng.

Điều kiện hoàn tất: có upgrade guide, rollback, health dashboard, support bundle đã khử secret và quy trình revoke/rotate.

## 14. Kiểm thử và nghiệm thu

### Unit/service

- Enrollment hết hạn, dùng lại, sai owner, revoke và rotate.
- Authenticate đúng/sai, replay, nonce, protocol version và payload vượt giới hạn.
- Command state transitions, timeout, duplicate ID, reconnect giữa lúc command chạy.
- Mapping event Connector sang PrinterManager callbacks.
- Permission và ownership trên từng route/command/file/camera.
- Không chứa secret trong log, response lỗi, metrics hoặc support bundle.

### Integration

- Connector giả lập kết nối WSS, ngắt mạng, reconnect và heartbeat timeout.
- Direct printer và connector printer cùng tồn tại trong một server.
- MQTT fake broker và fake FTPS server kiểm tra trạng thái/command/upload/download.
- File upload thất bại giữa chừng, checksum sai, URL hết hạn và cleanup staging.
- Test fresh DB và upgrade DB có dữ liệu cho SQLite và PostgreSQL.

### End-to-end thực tế

- Server trên VPS; Connector ở mạng nhà khác.
- Không mở port router; egress HTTPS/443 là đủ.
- Thêm máy in, theo dõi trạng thái, pause/resume, gửi 3MF, nhận archive.
- Rút mạng Connector và kiểm tra UI, sau đó khôi phục để xác nhận reconnect.
- Thu hồi Connector và xác nhận mọi credential/session bị vô hiệu hóa.

### Tiêu chí nghiệm thu tổng

- Connector không mở listener inbound trên mạng Internet.
- Revoke làm vô hiệu session hiện tại trong thời gian ngắn và ngăn reconnect.
- Không có lệnh hết hạn được thực thi khi Connector online lại.
- Không thất lạc trạng thái cuối sau reconnect: snapshot mới được gửi trước event tăng dần.
- Direct mode cũ không đổi hành vi.
- Không secret nào xuất hiện trong log ở test redaction.
- API connector có authentication, authorization, rate/size limit và audit.

## 15. Rủi ro và cách xử lý

| Rủi ro | Cách xử lý |
|---|---|
| Quá nhiều code đang kết nối trực tiếp IP | Inventory call site trước; transport adapter và migration theo capability |
| Connector mất mạng giữa lệnh | Command ID, trạng thái `delivery_unknown`, không tự phát lại lệnh nguy hiểm |
| Server chạy nhiều worker route sai Connector | Giai đoạn đầu giới hạn một instance; thiết kế lease/broker cho scale-out |
| Bị chiếm Connector | Credential riêng, revoke, quyền tối thiểu, không có shell/tunnel tùy ý, audit |
| Server bị lợi dụng làm proxy vào LAN người dùng | Chỉ allowlist lệnh; Connector chỉ thao tác printer đã bind; không nhận URL hoặc host tùy ý |
| FTPS passive mode/firewall | Chẩn đoán riêng, test mạng thực tế, không khẳng định chỉ cần cổng 443 cho đường Connector-to-printer |
| Camera tiêu thụ băng thông/tài nguyên | Snapshot trước, live session có TTL, giới hạn phiên/bitrate |
| Nâng cấp lệch phiên bản | `protocol_version`, minimum supported version và compatibility matrix |
| SQLite migration làm gián đoạn | Migration idempotent, backup trước upgrade và test database thực tế có dữ liệu |

## 16. Thứ tự công việc gần nhất

1. Thực hiện inventory chính xác các call site IP/access code trong repository; phân loại: status/control, transfer, camera, archive, diagnostics.
2. Viết protocol schema có version và fake Connector để xác thực luồng lệnh/sự kiện.
3. Implement quản lý enrollment/Connector trước; chưa điều khiển máy in.
4. Phát hành bản Connector prototype có Windows/Docker và chỉ hỗ trợ heartbeat/discovery.
5. Bổ sung transport cho status/control, sau đó lần lượt file transfer và camera.

Thứ tự này giảm rủi ro vì điểm khó nhất của hệ thống không phải discovery mà là chuyển các luồng đang dùng trực tiếp MQTT, FTPS và camera sang một đường vận chuyển từ xa, đồng thời giữ nguyên callbacks, archive và queue hiện tại.

## 17. Tài liệu và mã nguồn liên quan

- `docs/printbuddy-system-memory.md`
- `docs/printbuddy-codebase-index.md`
- `docs/printbuddy-provider-roadmap.md`
- `backend/app/models/printer.py`
- `backend/app/schemas/printer.py`
- `backend/app/core/database.py`
- `backend/app/api/routes/printers.py`
- `backend/app/services/printer_manager.py`
- `backend/app/services/printer_providers/base.py`
- `backend/app/services/printer_providers/factory.py`
- `backend/app/services/bambu_mqtt.py`
- `backend/app/services/bambu_ftp.py`
- `backend/app/services/background_dispatch.py`
- `backend/app/api/routes/camera.py`
- `backend/app/core/websocket.py`
- `backend/app/api/routes/websocket.py`
- `frontend/src/api/client.ts`
- `frontend/src/pages/PrintersPage.tsx`
- `docker-compose.yml`
