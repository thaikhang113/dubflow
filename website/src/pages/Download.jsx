import { Link } from 'react-router-dom'

import { Reveal } from '../components/motion'

// Kho phát hành khớp với `Settings.update_repo` của app desktop — đổi ở đây
// thì nhớ đổi cả bên đó, nếu không nút "Tải bản mới" trong app trỏ đi nơi khác.
const RELEASE_URL = 'https://github.com/YOUR_GITHUB/your-releases/releases/latest'

const REQUIREMENTS = [
  ['Hệ điều hành', 'Windows 10 hoặc 11, 64-bit'],
  ['Bộ nhớ', '8 GB RAM trở lên (16 GB thì mượt hơn)'],
  ['Ổ cứng', 'Khoảng 10 GB trống cho ứng dụng và mô hình'],
  ['Card đồ họa', 'Không bắt buộc. Có card NVIDIA thì chạy nhanh hơn nhiều'],
  ['Kết nối mạng', 'Cần cho bước tải video và bước dịch'],
]

export default function Download() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-14">
      <Reveal>
        <h1 className="text-3xl font-bold">Tải VoxDub Studio</h1>
        <p className="text-ink-soft mt-2.5">
          Bản dành cho Windows. Tải về, giải nén rồi chạy — không cần cài đặt.
        </p>
      </Reveal>

      <Reveal>
        <div className="card p-6 mt-8 glow border-primary/30">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-semibold">VoxDub Studio cho Windows</p>
            <p className="text-xs text-ink-muted mt-1">
              Bản mới nhất · 64-bit · khoảng 400 MB
            </p>
          </div>
          <a
            href={RELEASE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary px-5"
          >
            Tải xuống
          </a>
        </div>
        <p className="text-xs text-ink-muted mt-4 leading-relaxed">
          Liên kết mở trang phát hành trên GitHub — chọn tệp <code>.zip</code> mới
          nhất. Windows SmartScreen có thể cảnh báo vì tệp chưa ký số: bấm
          "Thông tin thêm" rồi "Vẫn chạy".
        </p>
        </div>
      </Reveal>

      <Reveal>
        <div className="card p-6 mt-4">
        <h2 className="font-semibold">Sau khi tải về</h2>
        <ol className="mt-3 space-y-2.5 text-sm text-ink-soft list-decimal list-inside leading-relaxed">
          <li>Giải nén thư mục ra ổ đĩa có nhiều chỗ trống (không chạy thẳng trong file zip)</li>
          <li>Chạy <strong className="text-ink">VoxDub.exe</strong> — trình cài đặt lần đầu tự mở</li>
          <li>Làm theo 4 bước: FFmpeg, giọng đọc VieNeu, nhận dạng Whisper, kích hoạt</li>
          <li>Máy mới có sẵn Vox dùng thử, bạn thử ngay được một video ngắn</li>
        </ol>
        <Link to="/huong-dan" className="btn-ghost mt-5 inline-flex text-xs py-2">
          Xem hướng dẫn chi tiết
        </Link>
        </div>
      </Reveal>

      <Reveal>
        <div className="card p-6 mt-4">
        <h2 className="font-semibold">Máy cần gì</h2>
        <dl className="mt-3 space-y-2.5">
          {REQUIREMENTS.map(([k, v]) => (
            <div key={k} className="flex flex-col sm:flex-row sm:gap-4 text-sm">
              <dt className="text-ink-muted sm:w-36 shrink-0">{k}</dt>
              <dd className="text-ink-soft">{v}</dd>
            </div>
          ))}
        </dl>
        </div>
      </Reveal>

      <Reveal>
        <div className="card p-6 mt-4 border-warn/25 bg-warn/5">
          <h2 className="font-semibold text-sm">Chưa có bản macOS và Linux</h2>
          <p className="text-ink-soft text-sm mt-1.5 leading-relaxed">
            Ứng dụng dùng một số thành phần chỉ chạy trên Windows. Chúng tôi chưa
            có kế hoạch cụ thể cho các hệ điều hành khác.
          </p>
        </div>
      </Reveal>
    </div>
  )
}
