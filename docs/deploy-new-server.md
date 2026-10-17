# Triển khai Printbuddy trên máy chủ mới

Hướng dẫn này dùng repository tùy chỉnh `quocanhcgd/Printbuddy`, nhánh `main`,
và Docker Compose trên máy chủ Linux mới. Không dùng nhánh hoặc repository
upstream nếu muốn triển khai các thay đổi riêng của Printbuddy.

## 1. Chuẩn bị máy chủ

Khuyến nghị Ubuntu Server 22.04/24.04 hoặc Debian 12, tối thiểu 2 CPU và 4 GB
RAM. Dung lượng đĩa phụ thuộc thư viện 3D và video; nên bắt đầu từ 40 GB và
dùng SSD. Máy chủ cần truy cập Internet để clone/build image và cần route tới
mạng máy in nếu Printbuddy phải truy cập máy in.

Cài Git, Docker Engine và Docker Compose plugin theo hướng dẫn chính thức của
bản phân phối/Docker. Xác nhận:

```bash
git --version
docker --version
docker compose version
```

Thêm tài khoản triển khai vào nhóm `docker` hoặc dùng `sudo` cho các lệnh
Docker. Quyền nhóm `docker` tương đương quyền root trên máy chủ.

## 2. Cho máy chủ quyền đọc GitHub

Repository riêng tư cần quyền xác thực. Khuyến nghị tạo SSH deploy key chỉ có
quyền đọc cho repository `quocanhcgd/Printbuddy`, cài public key vào GitHub,
rồi kiểm tra kết nối SSH. Không đặt personal access token trong URL clone,
`.env`, tài liệu hay lịch sử shell.

Clone repo và chuyển vào thư mục triển khai:

```bash
sudo mkdir -p /opt/printbuddy
sudo chown "$USER":"$USER" /opt/printbuddy
git clone --branch main git@github.com:quocanhcgd/Printbuddy.git /opt/printbuddy
cd /opt/printbuddy
```

Nếu dùng HTTPS, cấu hình Git Credential Manager hoặc credential helper trước,
không nhúng token vào lệnh `git clone`.

## 3. Cấu hình môi trường

```bash
cp .env.example .env
chmod 600 .env
```

Mở `.env`, đặt cấu hình production tối thiểu:

```env
DEBUG=false
LOG_LEVEL=INFO
LOG_TO_FILE=true
TZ=Asia/Ho_Chi_Minh
PUID=1000
PGID=1000
PORT=8000
```

`PUID`/`PGID` có thể đặt theo tài khoản triển khai bằng `id -u` và `id -g`.
Không đặt mật khẩu database hoặc token thật trong Git. SQLite trong Docker
volume là lựa chọn mặc định; chỉ cấu hình `DATABASE_URL` nếu đã chuẩn bị
PostgreSQL và backup riêng cho database đó. Giữ an toàn khóa MFA nếu tự cấu
hình `MFA_ENCRYPTION_KEY`; mất khóa có thể làm các bí mật MFA đã mã hóa không
thể giải mã.

## 4. Khởi chạy lần đầu

Trên Linux, Compose dùng `network_mode: host` để discovery và kết nối máy in
hoạt động. Chạy:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Theo dõi log khởi tạo:

```bash
docker compose logs -f --tail=200 printbuddy
```

Schema/migration được xử lý tự động khi ứng dụng khởi động. Mở giao diện tại
`http://<IP-máy-chủ>:8000` trong mạng tin cậy để hoàn tất thiết lập ban đầu,
bật xác thực và tạo/quản lý tài khoản.

## 5. Bảo vệ truy cập từ Internet

Không công khai HTTP không mã hóa trên cổng 8000. Đặt Caddy, Nginx hoặc reverse
proxy tương đương phía trước với HTTPS hợp lệ, giới hạn truy cập bằng firewall
hoặc VPN nếu phù hợp, và bật chuyển tiếp WebSocket để UI/Connector hoạt động.
Chỉ mở các cổng cần thiết trên firewall. Vì dịch vụ dùng host networking,
Printbuddy lắng nghe trực tiếp trên host; cấu hình firewall của máy chủ, không
chỉ firewall Docker.

Khi có DNS và reverse proxy, truy cập bằng URL HTTPS. Connector Windows cần
địa chỉ này để kết nối outbound WSS.

## 6. Sao lưu và cập nhật

Trước khi đưa vào sử dụng, lập lịch sao lưu thư mục `/app/data` trong volume
`printbuddy_data` ra thiết bị khác. Volume cùng máy chủ không phải bản sao lưu
khi ổ đĩa/máy chủ bị hỏng. Trước mỗi cập nhật, dùng script:

```bash
cd /opt/printbuddy
bash scripts/update-server.sh
```

Script mặc định cập nhật `main`. Có thể chọn nhánh đã checkout bằng biến:

```bash
PRINTBUDDY_BRANCH=main bash scripts/update-server.sh
```

Script từ chối chạy khi working tree có thay đổi chưa commit, chỉ fast-forward,
dừng dịch vụ để sao lưu nhất quán data volume, build/restart Compose, rồi chờ
health endpoint. Nếu build hoặc health check thất bại, script trả mã nguồn
về commit trước và thử dựng lại phiên bản cũ. Bản backup trước cập nhật được
giữ lại để xử lý thủ công; script không tự phục hồi database sau migration.

Không chạy song song hai lần cập nhật. Nếu dùng PostgreSQL bên ngoài, script
chỉ sao lưu volume Printbuddy; phải sao lưu PostgreSQL riêng trước khi nâng cấp.

## 7. Chẩn đoán thường gặp

```bash
docker compose ps
docker compose logs --tail=200 printbuddy
curl -v http://127.0.0.1:8000/health
```

- Không truy cập được UI: kiểm tra container, `PORT`, firewall và reverse proxy.
- Máy in không được tìm thấy: xác nhận máy chủ có route tới subnet máy in;
  có thể thêm IP thủ công hoặc cấu hình subnet bổ sung.
- Clone/pull báo `Permission denied (publickey)`: kiểm tra deploy key có quyền
  đọc repo và SSH agent của tài khoản triển khai.
- Cổng 8000 bị chiếm: chọn cổng khác trong `.env`, cập nhật reverse proxy và
  chạy lại Compose.
- Không gian đĩa thấp: kiểm tra Docker images, logs và dung lượng thư viện;
  không xóa volume dữ liệu để giải phóng dung lượng.

## Tham khảo

- Hướng dẫn cấu hình chung: [`../DEPLOYMENT.md`](../DEPLOYMENT.md)
- Cập nhật các loại cài đặt: [`../UPDATING.md`](../UPDATING.md)
- Compose production: [`../docker-compose.yml`](../docker-compose.yml)
