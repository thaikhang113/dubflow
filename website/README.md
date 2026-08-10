# VoxDub Website

Trang bán hàng + admin panel. React 18 + Vite + Tailwind, build ra tĩnh.
**Backend (control_server) serve luôn thư mục `dist/` cùng origin** — nên
frontend gọi API bằng đường dẫn tương đối, build một lần chạy được cả
localhost lẫn domain thật, không cần CORS, không cần build lại khi đổi domain.

## Cấu trúc

```
src/
  api/client.js        # REST client: api.* (public) và adminApi.* (X-Admin-Token)
  api/format.js        # định dạng tiền, Vox, ngày giờ tiếng Việt
  api/useFetch.js      # hook nạp dữ liệu có loading/lỗi/thử lại
  store/orders.js      # sổ đơn hàng của trình duyệt (localStorage)
  store/admin.js       # phiên admin (sessionStorage, zustand)
  components/          # PublicLayout, ui.jsx (Modal, Badge, CopyButton…)
  pages/               # trang public: Landing, Pricing, Buy, Checkout,
                       # MyOrders, Download, Docs, Faq, Contact
  pages/admin/         # AdminApp (nạp lười), Login, Dashboard, Devices,
                       # DeviceDetail, Orders, Keys, Providers, Config, AuditLog
```

## Chạy test local

```bash
cd website && npm ci && npm run build   # ra website/dist
cd ../control_server && npm start       # backend serve luôn dist
# Mở http://localhost:3001 — cả web lẫn API cùng một cổng.
```

Muốn sửa giao diện có hot-reload thì thêm: `cd website && npm run dev`
(http://localhost:5173, `/v1` được proxy sang backend).

Admin panel: `/admin` — đăng nhập bằng `ADMIN_TOKEN` trong
`control_server/.env`.

## Deploy lên máy chủ thật

1. `npm run build` → chép `website/dist/` lên máy chủ (cạnh `control_server/`,
   hoặc đặt `WEB_DIST` trong `.env` nếu để chỗ khác)
2. Sửa **duy nhất** `PUBLIC_URL` trong `control_server/.env` thành domain thật
3. Trỏ nginx theo `control_server/nginx-voxdub.conf` (proxy toàn bộ về cổng
   3001 — backend tự lo cả web lẫn API)

KHÔNG cần `.env.production` hay `VITE_API_URL` — chỉ dùng khi nào muốn host
website tách rời backend (xem `.env.example`).

## Luồng mua hàng (điểm cần biết khi sửa)

1. `Buy.jsx` tạo đơn → backend trả `accessToken` **đúng một lần** →
   `store/orders.js` cất vào localStorage NGAY, trước khi chuyển trang.
2. `Checkout.jsx` poll trạng thái đơn mỗi 4 giây kèm token. Không có token
   thì backend giấu `keyCode` — mã đơn 6 chữ số dò được nên không đủ để lấy
   hàng. Vì vậy mã kích hoạt CHỈ hiện trên trình duyệt đã tạo đơn (hoặc qua
   email).
3. `MyOrders.jsx` đọc sổ localStorage — không có "tài khoản" nào phía server.

## Admin

- Token gửi qua header `X-Admin-Token`, lưu `sessionStorage` (đóng tab là
  hết phiên — máy quản trị hay là máy dùng chung).
- An ninh thật nằm ở backend; lớp login ở đây chỉ để khỏi nhìn lỗi 401.
- Các thao tác tiền bạc (cộng Vox, duyệt đơn, chuyển máy) đều bắt buộc ghi
  lý do — backend ghi vào AuditLog vĩnh viễn.
