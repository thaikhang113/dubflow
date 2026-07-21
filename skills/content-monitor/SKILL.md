---
name: content-monitor
description: Theo dõi tự động kênh Douyin/TikTok bằng host Python + Chrome CDP thật. Dùng khi người dùng muốn thêm/xóa kênh theo dõi, bật/tắt monitor, xem danh sách kênh, chạy kiểm tra ngay, hoặc kiểm tra daemon.
---

# Skill: content-monitor

Theo dõi kênh Douyin định kỳ và gửi Telegram khi có video mới.

## Trạng thái runtime

- Script chạy trên **host SSD** bằng Python host, không chạy trong container OpenClaw.
- File skill nằm tại `/home/haonguyen/.openclaw/workspace/skills/content-monitor/`.
- Daemon dùng Chrome thật qua CDP `http://127.0.0.1:9222` khi `yt-dlp` không đọc được URL kênh Douyin.
- Không bypass login/captcha. Nếu Douyin bắt login/captcha thì người dùng xử lý thủ công trong Chrome CDP.

## File quan trọng

- `channels.json`: danh sách kênh theo dõi.
- `seen_videos.json`: video đã thấy, tránh báo trùng.
- `monitor.log`: log daemon.
- `daemon.pid`: PID khi daemon đang chạy.
- `content-monitor.py`: script chính.

## Lệnh host trực tiếp

```bash
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py --list
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py --status
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py --run-once
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py --prime-seen
setsid python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py --start --interval 60 >/tmp/content-monitor-daemon.log 2>&1 < /dev/null &
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py --stop
```

## Lệnh từ OpenClaw/container qua host runner

Khi OpenClaw đang ở container và không có Python, không được tự kết luận là không làm được. Hãy gọi host runner:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-status
/home/node/host-bin/openclaw-call-host-runner.sh monitor-list
/home/node/host-bin/openclaw-call-host-runner.sh monitor-run-once
/home/node/host-bin/openclaw-call-host-runner.sh monitor-start 60
/home/node/host-bin/openclaw-call-host-runner.sh monitor-stop
/home/node/host-bin/openclaw-call-host-runner.sh monitor-add "CHANNEL_URL" "CHANNEL_NAME"
/home/node/host-bin/openclaw-call-host-runner.sh monitor-remove "CHANNEL_URL_OR_NAME"
/home/node/host-bin/openclaw-call-host-runner.sh monitor-find "KEYWORD" 100
```

Quan trọng với Douyin:

- Không dùng browser/headless nội bộ của OpenClaw để search Douyin. Browser nội bộ có thể chạy ở port `18800`, headless, chưa login, và rất dễ bị captcha `验证码中间页`.
- Nếu thấy captcha trong browser nội bộ OpenClaw nhưng tab Chrome CDP thật `127.0.0.1:9222` vẫn mở được kênh, hãy bỏ qua browser nội bộ và gọi host runner `monitor-find`.
- Với yêu cầu tìm video trong kênh `消消漫`, lệnh đúng là:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-find "远古兽神" 100
```

## Thêm kênh

```bash
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py \
  --add-channel "URL_KENH_DOUYIN" --name "TEN_KENH"
```

Sau khi thêm kênh mới, nên chạy `--prime-seen` một lần nếu người dùng không muốn nhận thông báo cho các video cũ.

## Hủy theo dõi kênh

Khi người dùng yêu cầu hủy theo dõi/xóa kênh khỏi danh sách monitor, dùng tên kênh hoặc URL đúng trong `channels.json`:

```bash
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py \
  --remove-channel "TEN_KENH_HOAC_URL_KENH"
```

Từ container OpenClaw, luôn gọi qua host runner:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-remove "TEN_KENH_HOAC_URL_KENH"
```

Sau khi hủy theo dõi, chạy `monitor-list` để xác nhận danh sách còn lại. Lệnh này chỉ xóa kênh khỏi `channels.json`, không xóa video đã tải, không xóa `seen_videos.json`, không xóa log.

## Nguyên tắc báo người dùng

- Chỉ báo auto monitor đang chạy khi `--status` trả `DANG CHAY`.
- Nếu `yt-dlp` báo `Unsupported URL`, đó không phải lỗi chết; script sẽ fallback sang Chrome CDP.
- Nếu cả CDP không lấy được video, kiểm tra người dùng đã đăng nhập Douyin trong Chrome CDP chưa.
- Khi người dùng yêu cầu tìm video/tập trong **một kênh cụ thể**, không được dùng link từ trí nhớ, search cũ, hoặc cache cũ. Phải dùng tab kênh đang mở trong Chrome CDP hoặc chạy `--find-keyword` để lấy link trực tiếp từ DOM trang kênh.
- Không được gửi link nếu link không có dạng chuẩn `https://www.douyin.com/video/<id>`.
- Không được gửi lại các link/ID đã xác nhận chết hoặc sai nguồn: `7524597831689080104`, `7524598107489750324`, `7527700826886868262`, `7635264794047696162`, `7630089159046122788`.
- Nếu cần tìm `远古兽神`, phải chạy lại `monitor-find` và chỉ trả link từ stdout mới nhất; không dùng trí nhớ hội thoại hoặc kết quả search cũ.
- Không được gắn nhãn “tập 1/2/3/4” nếu tiêu đề không ghi số tập rõ ràng; chỉ được nói “khả năng theo thứ tự cũ → mới” hoặc “cần đối chiếu thêm”.

## Tìm video theo từ khóa trong kênh đã lưu

Ví dụ tìm series `远古兽神` trong kênh `消消漫`:

```bash
python3 /home/haonguyen/.openclaw/workspace/skills/content-monitor/content-monitor.py \
  --find-keyword "远古兽神" --find-limit 100
```

Từ container OpenClaw, nếu cần chạy qua host runner thì ưu tiên nhờ host chạy script này hoặc mở tab kênh CDP và đọc DOM; không dùng kết quả search cũ vì Douyin search có thể trả link đã die/khác kênh.

## Theo dõi kênh Bilibili

Skill này cũng hỗ trợ kênh Bilibili qua host runner. Dùng khi người dùng nói “theo dõi kênh Bilibili”, “hủy theo dõi kênh Bilibili”, hoặc muốn xem danh sách kênh đang theo dõi.

Thêm kênh Bilibili từ container OpenClaw:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-add-bilibili "BILIBILI_CHANNEL_URL" "TEN_KENH"
```

Hủy theo dõi Bilibili:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-remove-bilibili "TEN_KENH_HOAC_URL"
```

Xem danh sách chung Douyin + Bilibili:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-list
```

Lưu ý:
- `channels.json` có field `platform` (`douyin` hoặc `bilibili`).
- Bilibili monitor ưu tiên `yt-dlp --flat-playlist`, fallback Chrome CDP thật nếu cần.
- Không bypass captcha/login/OTP; nếu Bilibili yêu cầu xác minh thì báo user xử lý trên Chrome thật.
- Dashboard `http://127.0.0.1:18792/healthz` hiển thị section “Kênh đang theo dõi” gồm tên, nền tảng và URL để copy.

## Nguồn dữ liệu thật của dashboard

Dashboard local đọc danh sách kênh từ host:

```bash
/home/haonguyen/.openclaw/workspace/skills/content-monitor/channels.json
```

Vì vậy khi chạy trong Telegram/container:

- Không tự sửa `/home/node/.openclaw/workspace/skills/content-monitor/channels.json`.
- Không chạy trực tiếp `python3 content-monitor.py --remove-channel` trong container.
- Luôn dùng host runner để thêm/xóa kênh, vì host runner mới cập nhật đúng file host mà dashboard đọc:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh monitor-add-bilibili "URL" "TEN_KENH"
/home/node/host-bin/openclaw-call-host-runner.sh monitor-remove-bilibili "TEN_KENH_HOAC_URL"
/home/node/host-bin/openclaw-call-host-runner.sh monitor-add "URL_DOUYIN" "TEN_KENH"
/home/node/host-bin/openclaw-call-host-runner.sh monitor-remove "TEN_KENH_HOAC_URL"
```

Sau khi thêm/xóa, chạy `monitor-list` qua host runner rồi báo theo kết quả host-runner, không báo theo file container.

## Không dùng monitor để tìm tập Bilibili

`content-monitor` chỉ dùng để theo dõi kênh và báo video mới. Khi người dùng yêu cầu tìm `tập 0-3`, `tập 1`, hoặc số tập Bilibili cụ thể, không dùng `monitor-find` hoặc danh sách latest của kênh.

Hãy dùng skill `bilibili-vietnamese-dubber` với host runner:

```bash
/home/node/host-bin/openclaw-call-host-runner.sh bilibili-find-episodes "KEYWORD" "EPISODE_SPEC"
```
