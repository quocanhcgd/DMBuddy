# Truy cập trực tiếp camera Creality K3 qua WebRTC

Tài liệu này mô tả cách trình duyệt kết nối trực tiếp tới camera trên Creality K3 mà không cài thêm dịch vụ trên máy in. Nội dung đã được thử nghiệm với máy K3 tại địa chỉ `192.168.0.158`.

## Kết luận đã xác minh

- Service `webrtc_local` đang lắng nghe trên `0.0.0.0:8000`.
- Trình duyệt có thể thiết lập WebRTC trực tiếp với camera qua endpoint `POST /call/webrtc_local`.
- GET đến `/` trả `200 text/html` nhưng body rỗng. GET đến `/call/webrtc_local` trả `{}`. Các GET này không tạo luồng video.
- Firmware có các chuỗi HTML/JavaScript nhúng trong binary `webrtc_local`. Trang mẫu tạo `RTCPeerConnection`, tạo SDP offer, Base64 hóa JSON rồi POST đến `/call/webrtc_local`.
- Header của service cho phép `Access-Control-Allow-Origin: *` và `Content-Type` trong `Access-Control-Allow-Headers`.
- Trang HTML độc lập đã chạy trên trình duyệt và hiển thị hình camera trên máy K3 này.
- Hình ảnh truyền bằng WebRTC. Các gói SRTP được mã hóa theo cơ chế WebRTC; trình duyệt tự thương lượng và giải mã khi nhận luồng.

## Giao thức signaling

1. Tạo `RTCPeerConnection` trong trình duyệt và thêm transceiver video.
2. Tạo SDP offer và chờ ICE gathering hoàn tất.
3. Tạo JSON dạng `{"type":"offer","sdp":"<SDP>"}`.
4. Base64-encode JSON và POST chuỗi đó đến `http://<IP_K3>:8000/call/webrtc_local` với `Content-Type: plain/text`.
5. Response là JSON answer được Base64-encode. Decode, parse JSON rồi gọi `setRemoteDescription(answer)`.
6. Gán remote MediaStream từ sự kiện `track` vào phần tử `<video>`.

Firmware mẫu dùng `addTransceiver('video', {'direction': 'sendrecv'})`. Trang thử nghiệm trong repo dùng `recvonly` và đã hiển thị video trên máy được kiểm tra. Nếu gặp vấn đề tương thích trên model/firmware khác, hãy thử `sendrecv` để khớp với mẫu firmware.

## Ví dụ JavaScript tối thiểu

```js
async function connectK3Camera(host, video) {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
  });

  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.ontrack = event => {
    video.srcObject = event.streams[0] || new MediaStream([event.track]);
  };

  await pc.setLocalDescription(await pc.createOffer());
  if (pc.iceGatheringState !== 'complete') {
    await new Promise(resolve => {
      pc.addEventListener('icegatheringstatechange', () => {
        if (pc.iceGatheringState === 'complete') resolve();
      });
    });
  }

  const offer = btoa(JSON.stringify({
    type: 'offer',
    sdp: pc.localDescription.sdp,
  }));
  const response = await fetch(`http://${host}:8000/call/webrtc_local`, {
    method: 'POST',
    headers: { 'Content-Type': 'plain/text' },
    body: offer,
  });
  if (!response.ok) throw new Error(`K3 returned HTTP ${response.status}`);

  const answer = JSON.parse(atob(await response.text()));
  await pc.setRemoteDescription(answer);
  return pc;
}
```

Khi component bị gỡ bỏ hoặc cần dừng camera, gọi `pc.close()` và xóa `video.srcObject`.

## Thử nghiệm trực tiếp

Máy đã thử nghiệm:

```text
IP: 192.168.0.158
Board: CR0CUF039C13
Firmware: V4.0.3.1.13
Service: webrtc_local, TCP 8000
```

Trang HTML thử nghiệm độc lập trên máy kiểm thử đã thương lượng WebRTC trực tiếp với máy in. Không cần chạy `wget`, cài go2rtc, bật overlay, sửa Nginx hay cài service mới trên K3.

Lệnh SSH chỉ đọc để kiểm tra process đang lắng nghe:

```sh
netstat -lntp 2>/dev/null | grep ':8000'
```

Kết quả đã thấy trên máy thử nghiệm:

```text
tcp  0  0 0.0.0.0:8000  0.0.0.0:*  LISTEN  3886/webrtc_local
```

## Lưu ý khi nhúng vào web app

- Máy/ngữ cảnh trình duyệt phải có route mạng tới IP LAN của máy in.
- Request signaling HTTP và chính sách truy cập mạng nội bộ có thể bị hạn chế khi app chạy trên HTTPS. CORS của `webrtc_local` đã cho phép origin `*`, nhưng chính sách browser và mixed content vẫn có thể ảnh hưởng.
- Nếu app production chạy trên HTTPS, có thể đặt reverse proxy cùng origin để proxy request signaling tới K3. WebRTC media vẫn đi trực tiếp theo ICE giữa trình duyệt và máy in.
- Không expose cổng `8000` công khai ra Internet. Chỉ cho phép truy cập trong LAN/VPN tin cậy.
- SDP có thể chứa địa chỉ/candidate mạng nội bộ; không ghi log hoặc chia sẻ SDP nếu không cần thiết.
- Đã xác minh hiển thị hình trên một máy K3 với firmware nêu trên. Các board/firmware khác cần được thử lại.

## Nếu kết nối thất bại

Kiểm tra lần lượt:

1. Trình duyệt truy cập được `http://<IP_K3>:8000/` và nhận phản hồi HTTP. Trang gốc có thể trả body rỗng; điều này không kiểm tra được luồng video.
2. `webrtc_local` còn lắng nghe trên cổng 8000.
3. Request POST có `Content-Type: plain/text`; body là Base64 của JSON offer, không phải JSON thuần.
4. Response POST decode được thành JSON có `type` là `answer` và có trường `sdp`.
5. ICE gathering hoàn tất trước khi gửi offer; nếu cần, so sánh `sendrecv` với `recvonly`.
6. Trình duyệt không chặn request tới private network do policy của origin/app.

## Tích hợp vào Printbuddy

Printbuddy nhận diện máy Moonraker, Fluidd hoặc Mainsail có model chứa `K3` và
tự sinh nguồn camera:

```text
http://<IP-máy-in>:8000/call/webrtc_local
```

Nguồn này được đánh dấu `camera_type=webrtc`. Giao diện dùng player native
`RTCPeerConnection` cho endpoint `webrtc_local`: tạo offer `recvonly`, chờ ICE,
gửi offer Base64 và gán stream trả về vào thẻ `<video>`. Các camera WebRTC
Fluidd khác vẫn dùng player iframe hiện có, còn K2/K2 Plus vẫn đi qua go2rtc.

K3 hiện chỉ có luồng live WebRTC theo giao thức đã xác minh. Backend không thể
tự lấy JPEG từ WebRTC, vì vậy các chức năng cần ảnh đơn (thumbnail, timelapse,
plate detection và thông báo) cần một `external_camera_snapshot_url` riêng nếu
firmware sau này cung cấp endpoint snapshot. Nút Snapshot của camera K3 được
khóa để không gọi nhầm endpoint MJPEG của Printbuddy.
