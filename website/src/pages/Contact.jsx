import { Link } from 'react-router-dom'

// Biểu mẫu báo lỗi khớp với `Settings.support_url` trong app desktop.
const SUPPORT_FORM = 'https://example.com/support'
const SUPPORT_EMAIL = 'hotro@example.com'

export default function Contact() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-14">
      <h1 className="text-3xl font-bold">Liên hệ hỗ trợ</h1>
      <p className="text-ink-soft mt-2.5">
        Gửi kèm càng nhiều thông tin càng xử lý nhanh.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 mt-8">
        <a
          href={`mailto:${SUPPORT_EMAIL}`}
          className="card p-6 hover:border-border transition-colors"
        >
          <p className="font-semibold">Email</p>
          <p className="text-primary text-sm mt-1.5">{SUPPORT_EMAIL}</p>
          <p className="text-ink-muted text-xs mt-2">Thường trả lời trong ngày</p>
        </a>
        <a
          href={SUPPORT_FORM}
          target="_blank"
          rel="noopener noreferrer"
          className="card p-6 hover:border-border transition-colors"
        >
          <p className="font-semibold">Báo lỗi và góp ý</p>
          <p className="text-primary text-sm mt-1.5">Mở biểu mẫu</p>
          <p className="text-ink-muted text-xs mt-2">Dành cho lỗi kỹ thuật</p>
        </a>
      </div>

      <div className="card p-6 mt-4">
        <h2 className="font-semibold">Nên gửi kèm thông tin gì</h2>
        <div className="mt-4 space-y-4 text-sm">
          <div>
            <p className="text-ink font-medium">Nếu về thanh toán</p>
            <ul className="text-ink-soft mt-1.5 space-y-1 list-disc list-inside leading-relaxed">
              <li>Mã đơn hàng (dạng <code className="font-mono">VOX123456</code>)</li>
              <li>Thời điểm thanh toán và phương thức (QR, thẻ hay ví)</li>
              <li>4 số cuối tài khoản/thẻ đã dùng, nếu có</li>
            </ul>
          </div>
          <div>
            <p className="text-ink font-medium">Nếu muốn chuyển Vox sang máy mới</p>
            <ul className="text-ink-soft mt-1.5 space-y-1 list-disc list-inside leading-relaxed">
              <li>Mã máy cũ và mã máy mới — xem ở trang Tài khoản trong ứng dụng</li>
              <li>Máy mới cần mở ứng dụng ít nhất một lần trước khi chuyển</li>
              <li>Lý do đổi máy (hỏng ổ cứng, cài lại Windows…)</li>
            </ul>
          </div>
          <div>
            <p className="text-ink font-medium">Nếu về lỗi kỹ thuật</p>
            <ul className="text-ink-soft mt-1.5 space-y-1 list-disc list-inside leading-relaxed">
              <li>Nội dung thông báo lỗi (chụp màn hình được thì tốt nhất)</li>
              <li>Tệp nhật ký chẩn đoán: Cài đặt → Bảo trì → Xuất nhật ký chẩn đoán</li>
              <li>Link video đang xử lý, nếu lỗi chỉ xảy ra với video đó</li>
            </ul>
          </div>
        </div>
      </div>

      <p className="text-center text-sm text-ink-muted mt-8">
        Trước khi gửi, thử xem{' '}
        <Link to="/cau-hoi" className="text-primary hover:underline">
          câu hỏi thường gặp
        </Link>{' '}
        — phần lớn vướng mắc đã có sẵn câu trả lời ở đó.
      </p>
    </div>
  )
}
