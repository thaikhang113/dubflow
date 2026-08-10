import { Link } from 'react-router-dom'

import {
  AnimatedNumber, AuroraBackground, HoverLift, Reveal, Stagger, StaggerItem,
} from '../components/motion'

const STEPS = [
  {
    n: '01',
    title: 'Dán link hoặc chọn file',
    body: 'YouTube, TikTok, Douyin hoặc video có sẵn trên máy. Ứng dụng tự tải về.',
  },
  {
    n: '02',
    title: 'Nghe chép và tách nhạc nền',
    body: 'Whisper nghe lời thoại, Demucs tách giọng khỏi nhạc — nhạc nền và hiệu ứng gốc giữ nguyên.',
  },
  {
    n: '03',
    title: 'Dịch sang tiếng Việt',
    body: 'Bước duy nhất chạy qua máy chủ. Bản dịch bám ngữ cảnh video, canh vừa khung thời gian từng câu.',
  },
  {
    n: '04',
    title: 'Đọc giọng thật và ghép video',
    body: 'Giọng Việt tự nhiên, hơn 100 giọng nam nữ ba miền. Xuất MP4 kèm phụ đề nếu bạn muốn.',
  },
]

const FEATURES = [
  {
    title: 'Giữ nguyên nhạc nền',
    body: 'Tách giọng gốc bằng Demucs rồi chèn giọng Việt vào đúng chỗ — nhạc, tiếng động và hiệu ứng còn nguyên vẹn.',
  },
  {
    title: 'Hơn 100 giọng đọc',
    body: 'Giọng nam nữ ba miền, chạy ngay trên máy bạn. Có thể nhân bản giọng của chính bạn từ một đoạn ghi âm 10 giây.',
  },
  {
    title: 'Dịch bám ngữ cảnh',
    body: 'Máy chủ đọc hiểu cả video trước khi dịch: chủ đề, nhân vật, xưng hô và thuật ngữ được giữ nhất quán từ đầu tới cuối.',
  },
  {
    title: 'Phụ đề karaoke',
    body: 'Phụ đề rời hoặc ghi thẳng vào hình, có kiểu chữ nhảy theo lời đọc như trên TikTok.',
  },
  {
    title: 'Xử lý hàng loạt',
    body: 'Xếp hàng chục video vào danh sách rồi để máy chạy. Video nào xong trước xem trước.',
  },
  {
    title: 'Sửa từng câu',
    body: 'Trình chỉnh sửa có dạng sóng và bản xem trước: sửa lời dịch, đọc lại đúng câu đó, xuất lại.',
  },
]

function Stat({ value, suffix = '', label, animate = false }) {
  return (
    <div>
      <p className="text-2xl font-bold">
        {animate ? <AnimatedNumber value={value} /> : value}
        {suffix}
      </p>
      <p className="text-xs text-ink-muted mt-0.5">{label}</p>
    </div>
  )
}

export default function Landing() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <AuroraBackground />
        <div className="max-w-6xl mx-auto px-4 pt-20 pb-16 text-center">
          <Stagger gap={0.1}>
            <StaggerItem>
              <p className="inline-flex items-center gap-2 badge bg-primary/10 text-primary border border-primary/20 mb-5">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                Phiên bản 3.0 · 1.000 Vox = 10.000đ
              </p>
            </StaggerItem>
            <StaggerItem>
              <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight leading-[1.12]">
                Lồng tiếng video sang tiếng Việt
                <br className="hidden sm:block" />
                <span className="text-gradient"> chỉ với một đường link</span>
              </h1>
            </StaggerItem>
            <StaggerItem>
              <p className="mt-5 text-ink-soft max-w-2xl mx-auto leading-relaxed">
                Nghe chép, dịch, đọc giọng thật và ghép lại thành video hoàn chỉnh —
                giữ nguyên nhạc nền và hiệu ứng gốc. Mọi thứ chạy trên máy bạn,
                trừ bước dịch.
              </p>
            </StaggerItem>
            <StaggerItem>
              <div className="mt-8 flex flex-wrap gap-3 justify-center">
                <Link to="/tai-ve" className="btn-primary px-5 py-3 glow">
                  Tải ứng dụng cho Windows
                </Link>
                <Link to="/bang-gia" className="btn-ghost px-5 py-3">
                  Xem bảng giá
                </Link>
              </div>
              <p className="mt-4 text-xs text-ink-muted">
                Máy mới được tặng sẵn Vox dùng thử — không cần đăng ký tài khoản.
              </p>
            </StaggerItem>
          </Stagger>

          <Reveal delay={0.2}>
            <div className="mt-14 grid grid-cols-2 sm:grid-cols-4 gap-6 max-w-2xl mx-auto">
              <Stat value={100} suffix="+" label="Giọng đọc tiếng Việt" animate />
              <Stat value={10} suffix=" Vox" label="Mỗi câu thoại" animate />
              <Stat value="0 đ" label="Nghe chép và giọng đọc" />
              <Stat value="Windows" label="10 và 11, 64-bit" />
            </div>
          </Reveal>
        </div>
      </section>

      {/* Cách hoạt động */}
      <section className="max-w-6xl mx-auto px-4 py-16">
        <Reveal>
          <h2 className="text-2xl font-bold text-center">Cách hoạt động</h2>
          <p className="text-ink-soft text-sm text-center mt-2">
            Bốn bước, bạn chỉ làm bước đầu tiên.
          </p>
        </Reveal>
        <Stagger className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <StaggerItem key={s.n}>
              <HoverLift className="h-full">
                <div className="card-glass p-5 h-full">
                  <span className="text-primary font-mono text-xs font-bold">{s.n}</span>
                  <h3 className="font-semibold mt-2.5">{s.title}</h3>
                  <p className="text-ink-soft text-sm mt-1.5 leading-relaxed">{s.body}</p>
                </div>
              </HoverLift>
            </StaggerItem>
          ))}
        </Stagger>
      </section>

      {/* Tính năng */}
      <section className="max-w-6xl mx-auto px-4 py-16">
        <Reveal>
          <h2 className="text-2xl font-bold text-center">Có gì trong ứng dụng</h2>
        </Reveal>
        <Stagger className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <StaggerItem key={f.title}>
              <HoverLift className="h-full">
                <div className="card-glass p-5 h-full">
                  <h3 className="font-semibold">{f.title}</h3>
                  <p className="text-ink-soft text-sm mt-1.5 leading-relaxed">{f.body}</p>
                </div>
              </HoverLift>
            </StaggerItem>
          ))}
        </Stagger>
      </section>

      {/* Vì sao trả tiền theo câu */}
      <section className="max-w-6xl mx-auto px-4 py-16">
        <Reveal>
          <div className="card-glass p-8 sm:p-10">
            <div className="grid gap-8 md:grid-cols-2 items-center">
              <div>
                <h2 className="text-2xl font-bold">Trả tiền theo đúng thứ bạn dùng</h2>
                <p className="text-ink-soft mt-3 leading-relaxed text-sm">
                  Giá của mỗi video tính theo <strong className="text-ink">số câu
                  thoại</strong> — không phải theo tháng, không phải theo phút
                  video. Ứng dụng báo đúng một con số tổng ngay sau khi nghe chép
                  xong, trước khi trừ ví, và con số đó không đổi nữa.
                </p>
                <p className="text-ink-soft mt-3 leading-relaxed text-sm">
                  Không có tài khoản, không có gói thuê bao tự động gia hạn. Mua
                  bao nhiêu dùng bấy nhiêu, Vox không hết hạn.
                  <strong className="text-ink"> 1 Vox = 10đ</strong> — 1.000 Vox
                  chỉ 10.000đ.
                </p>
                <Link to="/bang-gia" className="btn-primary mt-6 inline-flex">
                  Xem bảng giá
                </Link>
              </div>
              <Stagger className="space-y-3" gap={0.06}>
                {[
                  ['Mỗi câu thoại trong video', '10 Vox'],
                  ['Bật dịch tự động qua máy chủ', '12 Vox/câu'],
                  ['Tạo tiêu đề + mô tả đăng bài', '+20 Vox'],
                  ['Nghe chép, giọng đọc, phụ đề, dựng video', 'Trong giá'],
                ].map(([label, price]) => (
                  <StaggerItem key={label} y={12}>
                    <div className="flex items-center justify-between bg-input rounded-xl px-4 py-3">
                      <span className="text-sm text-ink-soft">{label}</span>
                      <span
                        className={`text-sm font-semibold ${
                          price === 'Trong giá' ? 'text-ok' : 'text-primary'
                        }`}
                      >
                        {price}
                      </span>
                    </div>
                  </StaggerItem>
                ))}
              </Stagger>
            </div>
          </div>
        </Reveal>
      </section>

      {/* Hàng tin cậy */}
      <section className="max-w-6xl mx-auto px-4 pb-4">
        <Reveal>
          <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs text-ink-muted">
            <span className="inline-flex items-center gap-2">
              <svg viewBox="0 0 24 24" className="w-4 h-4 text-ok" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6l-8-4Z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
              Thanh toán an toàn qua PayOS
            </span>
            <span>Nhận mã kích hoạt tức thì</span>
            <span>Vox không hết hạn</span>
            <span>Không cần tài khoản</span>
          </div>
        </Reveal>
      </section>

      {/* CTA cuối */}
      <section className="max-w-6xl mx-auto px-4 py-12">
        <Reveal>
          <div className="relative overflow-hidden card-glass p-10 text-center">
            <AuroraBackground />
            <h2 className="text-2xl font-bold">Thử miễn phí ngay</h2>
            <p className="text-ink-soft text-sm mt-2.5 max-w-xl mx-auto">
              Tải ứng dụng, mở lên là chạy được — máy mới có sẵn Vox dùng thử,
              đủ cho một video ngắn.
            </p>
            <Link to="/tai-ve" className="btn-primary mt-6 px-5 py-3 inline-flex glow">
              Tải VoxDub Studio
            </Link>
          </div>
        </Reveal>
      </section>
    </>
  )
}
