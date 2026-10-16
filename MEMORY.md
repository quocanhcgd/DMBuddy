# Printbuddy Working Memory

Đây là điểm vào ngắn cho các phiên điều chỉnh tiếp theo. Bản mô tả đầy đủ nằm ở:

- [`docs/printbuddy-system-memory.md`](docs/printbuddy-system-memory.md): kiến trúc, runtime, dữ liệu, luồng sự kiện, tích hợp, rủi ro và quy trình sửa.
- [`docs/printbuddy-codebase-index.md`](docs/printbuddy-codebase-index.md): bản đồ thư mục, phạm vi mã nguồn, route/module chính và lệnh kiểm tra.

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
- Discovery route hiện đã đi qua `backend/app/services/printer_transport.py`: `ConnectorPrinterTransport` kiểm tra result/timeout và không fallback âm thầm sang direct; `DirectPrinterTransport` trả `capability_unavailable` cho discovery chưa triển khai. Status/control/file adapters vẫn là phần tiếp theo.
- Đã thêm typed RPC `printer.verify.request/result` và `printer.status.request/result`. Discovery/status không nhận credential; provider verify nhận access code/token chỉ trong request WSS ngắn hạn, xử lý trong memory và không lưu/log/echo. API tạo printer ở `connection_mode=connector` bắt buộc verify trước khi lưu; application-level encryption riêng cho credential và UI wizard discovery → add vẫn chưa hoàn tất.
- Các task Phase 0-1 đã triển khai một phần được đánh dấu `DOING`/`DONE` trong task plan; transport, status/control, file, camera và packaging production vẫn chưa triển khai hoàn chỉnh.

## GitHub và đồng bộ mã nguồn

- Repository riêng tư lưu mã nguồn tùy chỉnh: [quocanhcgd/Printbuddy](https://github.com/quocanhcgd/Printbuddy).
- Local repository dùng nhánh `main`, remote `origin` qua HTTPS và đã push commit khởi tạo.
- Quy trình cập nhật: kiểm tra thay đổi và secret → chạy test phù hợp → `git add`/`git commit` → `git push origin main`.
- Không đưa dữ liệu runtime hoặc thông tin nhạy cảm lên GitHub: `data/`, `archive/`, `logs/`, `*.db`, `.env`, credential/token/key runtime đã được loại bởi `.gitignore`.
- Repository upstream gốc vẫn được tham chiếu trong tài liệu; không đổi các định danh kỹ thuật của ứng dụng chỉ vì repository tùy chỉnh này.

