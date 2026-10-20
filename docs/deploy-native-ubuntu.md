# Cài đặt Printbuddy native trên Ubuntu (không dùng Docker)

Tài liệu này dành cho Ubuntu Server 22.04/24.04 khi máy chủ hiện chỉ dùng
`root`. Ứng dụng được chạy bằng `systemd`, Python virtualenv và Node.js chỉ
dùng để build frontend.

## 1. Điều kiện

- Ubuntu Server 22.04 hoặc 24.04
- Tối thiểu 2 CPU, 4 GB RAM và khoảng 10 GB trống (nhiều hơn nếu lưu 3MF)
- Máy chủ có Internet để cài package và clone GitHub
- Máy chủ có route đến mạng máy in nếu cần kết nối Moonraker/Bambu
- Repository: `https://github.com/quocanhcgd/DMBuddy.git`

Đăng nhập SSH và chuyển sang root:

```bash
sudo -i
```

## 2. Cài package hệ thống

```bash
apt update
apt install -y git curl ca-certificates ffmpeg \
  python3 python3-pip python3-venv build-essential

# Frontend hiện yêu cầu Node.js 20 trở lên; dùng Node.js 22 LTS.
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs

python3 --version
node --version
npm --version
```

## 3. Lấy mã nguồn

Nếu repository là private, cấu hình SSH deploy key trước rồi thay URL HTTPS
bằng URL SSH. Không đặt personal access token trực tiếp trong URL.

```bash
mkdir -p /opt

if [ -d /opt/printbuddy/.git ]; then
  cd /opt/printbuddy
  git remote set-url origin https://github.com/quocanhcgd/DMBuddy.git
  git fetch origin
  git checkout main
  git reset --hard origin/main
else
  git clone --branch main \
    https://github.com/quocanhcgd/DMBuddy.git /opt/printbuddy
  cd /opt/printbuddy
fi
```

Không chạy `chown printbuddy:printbuddy` trong quy trình root-only này vì máy
không tạo user `printbuddy`.

## 4. Cài backend Python

```bash
cd /opt/printbuddy
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip wheel
./venv/bin/pip install -r requirements.txt
```

## 5. Build frontend

```bash
cd /opt/printbuddy/frontend
npm ci
npm run build
cd /opt/printbuddy
```

Sau bước này phải có `/opt/printbuddy/static/index.html` và thư mục
`/opt/printbuddy/static/assets`.

## 6. Tạo thư mục dữ liệu và cấu hình

SQLite mặc định được tạo trong `DATA_DIR/printbuddy.db`. Không đặt dữ liệu
trong thư mục tạm hoặc trong `frontend`.

```bash
mkdir -p /opt/printbuddy/data /opt/printbuddy/logs
chmod 700 /opt/printbuddy/data /opt/printbuddy/logs

cat > /opt/printbuddy/.env <<'EOF'
DEBUG=false
LOG_LEVEL=INFO
LOG_TO_FILE=true
EOF
chmod 600 /opt/printbuddy/.env
```

Nếu cần PostgreSQL, chỉ thêm `DATABASE_URL` sau khi đã chuẩn bị PostgreSQL và
backup riêng. Cài native mặc định dùng SQLite, không cần SQL server.

## 7. Tạo systemd service

Service dưới đây chạy bằng root để tương thích máy hiện tại và để virtual
printer có thể bind các cổng thấp như 990. Khi hệ thống ổn định, nên chuyển
sang user riêng.

```bash
cat > /etc/systemd/system/printbuddy.service <<'EOF'
[Unit]
Description=Printbuddy - 3D Printer Management
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/printbuddy
EnvironmentFile=-/opt/printbuddy/.env
Environment="DATA_DIR=/opt/printbuddy/data"
Environment="LOG_DIR=/opt/printbuddy/logs"
Environment="TZ=Asia/Ho_Chi_Minh"
Environment="PORT=8000"
ExecStart=/opt/printbuddy/venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable printbuddy
systemctl start printbuddy
systemctl status printbuddy --no-pager
```

## 8. Kiểm tra lần đầu

```bash
curl --fail http://127.0.0.1:8000/health
ss -lntp | grep ':8000'
journalctl -u printbuddy -n 100 --no-pager
tail -f /opt/printbuddy/logs/printbuddy.log
```

Kết quả health mong đợi:

```json
{"status":"healthy"}
```

Mở giao diện tại `http://IP_UBUNTU:8000`. Nếu chỉ truy cập qua reverse
proxy, có thể bind Uvicorn vào `127.0.0.1` thay vì `0.0.0.0`.

## 9. Firewall

Nếu dùng UFW, mở web port cho mạng quản trị. Không mở toàn Internet nếu không
có HTTPS/reverse proxy:

```bash
ufw allow OpenSSH
ufw allow from 192.168.0.0/16 to any port 8000 proto tcp
ufw enable
ufw status
```

Nếu bật Virtual Printer, các client slicer phải đến được các cổng sau trên IP
bind của Printbuddy:

| Cổng | Giao thức | Mục đích |
|---:|---|---|
| 990 | TCP | implicit FTPS |
| 8883 | TCP | MQTT TLS |
| 3000, 3002 | TCP | bind/discovery |
| 2021 | UDP | SSDP discovery |
| 50000-50100 | TCP | FTP passive data |
| 6000, 322 | TCP | proxy file/camera mode |
| 2024-2026 | TCP | auxiliary Bambu ports khi proxy mode cần |

Chỉ mở các cổng này trong LAN tin cậy và chỉ khi tính năng tương ứng được
bật. Moonraker thường cần máy chủ truy cập outbound đến `IP_MAY_IN:7125`.

## 10. Sao lưu dữ liệu

Dừng service trước khi sao lưu SQLite để có bản nhất quán:

```bash
systemctl stop printbuddy
tar czf /root/printbuddy-$(date +%Y%m%d-%H%M%S).tgz \
  -C /opt/printbuddy data .env
systemctl start printbuddy
```

Không đưa file backup, `.env`, JWT secret hoặc MFA key lên GitHub.

## 11. Cập nhật từ GitHub

Nên dùng helper có sẵn vì nó dừng service, tạo backup API tùy chọn, cập nhật
dependencies, build frontend và khởi động lại:

```bash
cd /opt/printbuddy
BACKUP_MODE=auto bash install/update.sh
```

Nếu muốn bỏ qua backup API:

```bash
cd /opt/printbuddy
BACKUP_MODE=skip bash install/update.sh
```

Nếu update thất bại:

```bash
systemctl status printbuddy --no-pager
journalctl -u printbuddy -n 200 --no-pager
cd /opt/printbuddy
git status
```

Script update có thể `git reset --hard origin/main`; mọi chỉnh sửa trực tiếp
trên máy chủ sẽ bị xóa sau khi xác nhận. Hãy commit/push thay đổi trước khi
cập nhật.

## 12. Lệnh vận hành thường dùng

```bash
systemctl restart printbuddy
systemctl stop printbuddy
systemctl start printbuddy
systemctl status printbuddy --no-pager
journalctl -u printbuddy -f
curl -v http://127.0.0.1:8000/health
ss -lntup | grep -E ':(8000|990|8883|3000|3002|6000|322|2024|2025|2026)\\b'
```

Nếu service báo `ModuleNotFoundError`, kiểm tra `WorkingDirectory` là
`/opt/printbuddy` và Uvicorn là `/opt/printbuddy/venv/bin/uvicorn`. Nếu UI
trắng hoặc trả 404, chạy lại `npm ci && npm run build` trong `frontend` rồi
`systemctl restart printbuddy`.

