# VoxDub SaaS Backend

Máy chủ duy nhất giữ API key của các mô hình AI. Ứng dụng desktop gửi câu
thoại thô lên đây; máy chủ chọn mô hình, dựng lời nhắc, gọi mô hình, trừ Vox
và trả về bản dịch. App không biết gì về provider/model/key.

**Stack:** Node 20+ · Fastify 5 · MongoDB 7 · Mongoose 8

Backend cũng **serve luôn website** (`website/dist`) trên cùng cổng — một
process, một cổng, cả web lẫn API. Chuyển từ test local sang domain thật chỉ
cần đổi `PUBLIC_URL` trong `.env` (và trỏ nginx về cổng 3001).

---

## Mô hình kinh doanh

Không có tài khoản người dùng. **Chiếc máy là danh tính.**

```
WEB:  chọn gói (hoặc nhập số tiền) → link thanh toán PayOS (QR/thẻ/ví)
      → PayOS webhook (chữ ký HMAC) → sinh key VOX-XXXX-XXXX-XXXX
      → hiện trên web + gửi mail

APP:  mở lần đầu → tự đăng ký thiết bị → tặng 200 Vox dùng thử
      → Tài khoản → dán key → +N Vox
      → dịch video → trừ Vox theo số câu
```

**Một key = một lần = một máy.** Ràng buộc này nằm ở tầng dữ liệu
(`ActivationKey.status` chuyển `issued → used` trong một lệnh nguyên tử),
không phải một lệnh `if` có thể quên.

Credit gắn với `Device.fingerprint` = SHA-256(MachineGuid | hostname | arch).
Cài lại app hay xóa `.env` đều không mất Vox. Đổi máy thì admin chuyển tay
qua `POST /v1/admin/devices/:fp/transfer` (có ghi nhật ký).

---

## Cài đặt

```bash
cd control_server
npm ci
cp .env.example .env      # rồi điền giá trị thật

# Sinh 3 secret bắt buộc:
openssl rand -hex 32      # → JWT_SECRET
openssl rand -hex 32      # → ADMIN_TOKEN
openssl rand -hex 32      # → APP_ENCRYPTION_KEY (phải đúng 64 ký tự hex)

npm run indexes           # tạo index MongoDB (chạy một lần khi deploy)
npm run seed              # nạp cấu hình mặc định + provider đầu tiên
npm start
```

Thiếu `MONGODB_URI`, `JWT_SECRET` hay `APP_ENCRYPTION_KEY` thì server **thoát
ngay lúc khởi động** kèm thông báo — không để lỗi cấu hình lộ ra lúc 3 giờ
sáng ở giữa một lượt dịch.

### Test local (đã cấu hình sẵn)

`.env.example` mặc định đã trỏ hết về localhost: MongoDB không auth,
`PUBLIC_URL=http://localhost:3001`. Chạy `npm start` rồi mở
`http://localhost:3001` — có cả trang bán hàng lẫn admin panel (`/admin`,
đăng nhập bằng `ADMIN_TOKEN` trong `.env`). Muốn app desktop gọi server
local: đặt `VOXDUB_API_URL=http://localhost:3001` trong `.env` gốc dự án
(chỉ có tác dụng khi chạy từ mã nguồn; bản exe dùng địa chỉ nhúng lúc build).

### MongoDB

```bash
mongosh admin --eval '
db.createUser({
  user: "voxdub",
  pwd: "<mật khẩu mạnh>",
  roles: [{ role: "readWrite", db: "voxdub" }]
})'
```

Không mở cổng 27017 ra ngoài. Backend nói chuyện với MongoDB qua localhost.

### Thêm nơi gọi mô hình

```bash
curl -X POST http://localhost:3001/v1/admin/providers \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "openrouter",
    "label": "OpenRouter",
    "role": "translate",
    "type": "openai_compat",
    "baseUrl": "https://openrouter.ai/api/v1",
    "apiKey": "sk-or-v1-...",
    "model": "google/gemini-2.5-flash",
    "priority": 1
  }'
```

`apiKey` được mã hóa AES-256-GCM trước khi lưu; khóa mã hóa nằm trong
`.env`, không nằm trong DB. Dump database rò ra ngoài cũng không lộ key.

Thêm provider thứ hai với `priority` lớn hơn để có dự phòng: provider đầu
lỗi thì gateway tự rơi xuống provider sau, người dùng không thấy gián đoạn.

---

## API

Prefix `/v1`. App gửi `Authorization: Bearer <device token>`.
Admin gửi `X-Admin-Token: <ADMIN_TOKEN>`.

### Công khai

| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | `{ok, version, uptimeS}` cho monitoring |
| GET | `/v1/config/app` | Bảo trì, phiên bản tối thiểu, bảng giá |
| GET | `/v1/billing/packages` | Gói bán sẵn + quy tắc số tiền tùy chỉnh |
| POST | `/v1/billing/orders` | Tạo đơn → trả `orderCode` + link thanh toán PayOS |
| GET | `/v1/billing/orders/:code` | Trạng thái đơn (web poll trong lúc chờ) |
| POST | `/v1/billing/webhook/payos` | PayOS báo thanh toán thành công (chữ ký HMAC-SHA256) |

### Thiết bị

| Method | Path | Mô tả |
|---|---|---|
| POST | `/v1/device/register` | Đăng ký máy → device token (+ tặng Vox lần đầu) |
| POST | `/v1/device/refresh` | Đổi token sắp hết hạn lấy token mới |
| GET | `/v1/device/me` | Thông tin máy + số dư |
| POST | `/v1/device/activate` | Kích hoạt mã → cộng Vox |
| GET | `/v1/device/balance` | Số Vox hiện tại |
| GET | `/v1/device/history` | Lịch sử sổ cái (phân trang) |
| POST | `/v1/device/estimate` | Ước tính Vox cho một video trước khi chạy |

### AI Gateway

| Method | Path | Vox |
|---|---|---|
| POST | `/v1/ai/translate` | 1/câu |
| POST | `/v1/ai/analyze` | 2/video |
| POST | `/v1/ai/review` | 1/câu ĐƯỢC SỬA |
| POST | `/v1/ai/generate-post` | 5/video |

Mọi route đều nhận `jobId`. Gửi lại cùng `jobId` trả về kết quả cũ và
**không trừ Vox lần hai** — app rớt mạng giữa chừng không biết request đã
tới nơi hay chưa, đây là thứ duy nhất khiến việc thử lại an toàn.

Mã lỗi app cần xử lý:

```
402 INSUFFICIENT_CREDIT  { balance, required }   → mời nạp
503 MAINTENANCE          { message }             → hiện thông báo, chặn
503 AI_UNAVAILABLE       { retryAfter }          → thử lại
429 (rate limit)                                 → chờ rồi thử lại
403 DEVICE_BLOCKED       { message }             → liên hệ hỗ trợ
```

### Admin

```
GET    /v1/admin/devices                  danh sách máy (tìm, lọc, phân trang)
GET    /v1/admin/devices/:fp              chi tiết + sổ cái + lịch sử dùng
PATCH  /v1/admin/devices/:fp/status       khóa/mở máy (thu hồi token ngay)
POST   /v1/admin/devices/:fp/credit       cộng/trừ Vox tay
POST   /v1/admin/devices/:fp/transfer     chuyển toàn bộ Vox sang máy mới
GET    /v1/admin/keys                     danh sách mã
POST   /v1/admin/keys                     phát mã tay (bồi thường, KOL…)
DELETE /v1/admin/keys/:code               thu hồi mã CHƯA dùng
GET    /v1/admin/orders                   đơn hàng
POST   /v1/admin/orders/:code/approve     duyệt tay (webhook PayOS lỗi/gián đoạn)
GET    /v1/admin/config                   toàn bộ AppConfig
PUT    /v1/admin/config/:key              sửa một khóa
GET    /v1/admin/providers                nơi gọi mô hình (KHÔNG trả apiKey)
POST   /v1/admin/providers                thêm
PATCH  /v1/admin/providers/:id            sửa (apiKey rỗng = giữ key cũ)
DELETE /v1/admin/providers/:id            xóa
GET    /v1/admin/analytics/overview       doanh thu, máy, Vox, lượt gọi
GET    /v1/admin/analytics/usage          thống kê theo ngày
GET    /v1/admin/audit-log                nhật ký hành động
```

---

## Cấu hình lúc chạy (AppConfig)

Sửa qua `PUT /v1/admin/config/:key`, có hiệu lực trong vòng 60 giây
(cache TTL), không cần restart.

| Khóa | Mặc định | Ý nghĩa |
|---|---|---|
| `credit.enabled` | `true` | `false` = mọi thứ miễn phí, bỏ qua toàn bộ tầng credit |
| `credit.vox.to.vnd` | `10` | Tỷ giá chuẩn: 1 Vox = 10đ (1.000 Vox = 10.000đ) |
| `trial.vox` | `2000` | Tặng lần đầu mỗi máy (0 = tắt) |
| `trial.upfront.vox` / `trial.defer.hours` | `500` / `24` | Chống farm trial: tặng ngay một phần, phần còn lại chờ máy sống đủ giờ |
| `credit.cost.segment.base` | `10` | Giá công khai mỗi câu thoại (segment) |
| `credit.cost.segment.autotranslate` | `2` | Cộng thêm mỗi segment khi bật dịch tự động (10 → 12) |
| `credit.cost.metadata` | `20` | Gói tiêu đề + mô tả đăng bài, trọn gói mỗi video |
| `internal.cost.*` | | Giá nội bộ ghi `CreditHold.usage` để đối soát — KHÔNG trừ ví khi có hold |
| `hold.enabled` / `hold.ttl.hours` | `true` / `48` | Giữ chỗ Vox sau ASR, hết hạn tự hoàn |
| `credit.packages` | 5 gói | Mảng `{id, label, vnd, vox, bonus, popular}` — đổi trên DB cũ dùng `npm run billing:update` |
| `order.min.vnd` / `order.max.vnd` | `10000` / `20000000` | Biên số tiền tùy chỉnh |
| `order.expire.minutes` | `60` | |
| `maintenance.mode` | `false` | Chặn mọi request AI |
| `min.app.version` | `3.0.0` | App cũ hơn bị buộc cập nhật |
| `ai.max.segments.per.request` | `120` | Trần cứng, app không đổi được |
| `ai.max.chars.per.segment` | `800` | |

---

## Vận hành

### Tiền vào mà không có key?

Với PayOS, đơn khớp tự động theo mã số — không còn cảnh ghi sai nội dung
chuyển khoản. Trường hợp hiếm còn lại: webhook không tới nơi (PayOS bảo trì,
server restart đúng lúc). Đối chiếu trong PayOS Dashboard rồi duyệt tay:

```bash
# Tìm đơn đang chờ
curl -H "X-Admin-Token: $T" '.../v1/admin/orders?status=pending'
# Đối chiếu giao dịch trong PayOS Dashboard rồi duyệt
curl -X POST -H "X-Admin-Token: $T" '.../v1/admin/orders/VOX123456/approve' \
  -d '{"note":"Webhook lỗi, đã đối chiếu PayOS ref FT123 lúc 14:32"}'
```

Số tiền webhook lệch với đơn (gần như không thể với PayOS) thì hệ thống
KHÔNG cấp key, chỉ ghi `order.amount_mismatch` vào audit log.

### Đăng ký webhook PayOS (một lần sau deploy)

```bash
# Server phải đang chạy, PUBLIC_URL phải là HTTPS công khai
npm run payos:confirm-webhook
```

### Người dùng đổi máy

```bash
# Máy mới phải mở app ít nhất một lần (để có bản ghi Device)
curl -X POST -H "X-Admin-Token: $T" '.../v1/admin/devices/<fp-cũ>/transfer' \
  -d '{"toFingerprint":"<fp-mới>","reason":"Hỏng ổ cứng, có hóa đơn"}'
```

Máy cũ bị khóa luôn sau khi chuyển — nếu không thì một lần "đổi máy" thành
hai máy dùng chung một ví.

### Backup

```bash
# Cron 3:00 sáng
mongodump --uri="mongodb://voxdub:pwd@localhost/voxdub" --out=/backup/$(date +%Y%m%d)
find /backup -mtime +7 -exec rm -rf {} \;
```

`CreditLedger` là sổ tiền, lưu vĩnh viễn, chỉ ghi thêm. `UsageLog` tự xóa
sau 90 ngày (dữ liệu vận hành). `AuditLog` không có TTL.

### Kiểm thử

```bash
npm test     # tiện ích thuần: mã kích hoạt, mã hóa, đọc JSON của mô hình
```

Không cần MongoDB. Các test cần DB nên chạy trên môi trường staging riêng.

---

## Ghi chú thiết kế

**Không dùng transaction MongoDB.** Máy chủ chạy MongoDB đơn (không replica
set) nên không có transaction nhiều tài liệu. Thay vào đó, trừ credit là
**một lệnh `findOneAndUpdate` có điều kiện** `balance >= amount` — nguyên tử
theo bảo đảm của MongoDB trên một tài liệu. Hai request đồng thời thì đúng
một cái thắng. Số dư không bao giờ âm, và không cần khóa.

**Trừ SAU khi mô hình trả lời.** Mô hình lỗi thì người dùng không mất gì.
Rủi ro ngược lại (gọi xong, chưa kịp trừ thì server chết) được `UsageLog`
ghi lại để đối chiếu — và nó hiếm hơn nhiều so với việc mô hình lỗi.

**Ngữ cảnh người dùng là DỮ LIỆU, không phải mệnh lệnh.** Domain, xưng hô,
glossary do người dùng gửi lên được cắt độ dài, bỏ thẻ HTML và fence, rồi
đặt trong một khối có nhãn rõ ràng nằm SAU system prompt. Câu "ignore all
previous instructions" trong đó chỉ là một dòng chữ mô tả video.
