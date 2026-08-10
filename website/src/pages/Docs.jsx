import { Link } from 'react-router-dom'

function Section({ title, children }) {
  return (
    <section className="card p-6">
      <h2 className="font-semibold text-lg">{title}</h2>
      <div className="mt-3 space-y-3 text-sm text-ink-soft leading-relaxed">
        {children}
      </div>
    </section>
  )
}

function Step({ n, title, children }) {
  return (
    <div className="flex gap-4">
      <span className="shrink-0 w-7 h-7 rounded-lg bg-primary/15 text-primary grid place-items-center text-xs font-bold">
        {n}
      </span>
      <div className="min-w-0">
        <p className="font-medium text-ink">{title}</p>
        <div className="mt-1 space-y-2">{children}</div>
      </div>
    </div>
  )
}

function Cmd({ children }) {
  return (
    <pre className="bg-input border border-border-subtle rounded-lg px-3 py-2 text-xs font-mono overflow-x-auto">
      {children}
    </pre>
  )
}

export default function Docs() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-14 space-y-5">
      <div>
        <h1 className="text-3xl font-bold">Hướng dẫn cài đặt</h1>
        <p className="text-ink-soft mt-2.5">
          Mỗi bước chỉ làm một lần. Cài tối thiểu bước 1 và bước 3 là chạy được.
        </p>
      </div>

      <Section title="Bước 1 — Cài FFmpeg">
        <p>
          FFmpeg lo phần ghép hình và tiếng. Mở <strong className="text-ink">PowerShell</strong>{' '}
          (bấm phím Windows, gõ <code>powershell</code>, Enter) rồi chạy:
        </p>
        <Cmd>winget install Gyan.FFmpeg</Cmd>
        <p>
          Đóng PowerShell và mở lại, gõ <code>ffmpeg -version</code> — thấy số
          phiên bản là được.
        </p>
        <p className="text-ink-muted text-xs">
          Không dùng được winget? Tải bản "release full" tại gyan.dev, giải nén,
          rồi chép <code>ffmpeg.exe</code> và <code>ffprobe.exe</code> vào cùng
          thư mục với VoxDub.exe — ứng dụng tự nhận.
        </p>
      </Section>

      <Section title="Bước 2 — Cài Python">
        <p>Cần Python để cài bộ giọng đọc ở bước sau.</p>
        <Cmd>winget install Python.Python.3.12</Cmd>
        <p>
          Đóng và mở lại PowerShell, gõ <code>py --version</code>. Máy đã có
          Python 3.10 tới 3.12 thì bỏ qua bước này.
        </p>
      </Section>

      <Section title="Bước 3 — Cài giọng đọc VieNeu">
        <p>
          Đúp chuột vào tệp <strong className="text-ink">Cai dat giong VieNeu.bat</strong>{' '}
          trong thư mục VoxDub Studio.
        </p>
        <p>
          Script tự tạo môi trường riêng và tải mô hình (khoảng 300 MB). Mất
          vài phút, không cần card đồ họa — đây là bộ giọng đọc của ứng dụng
          với hơn 100 giọng nam nữ ba miền.
        </p>
      </Section>

      <Section title="Bước 4 — Vox và mã kích hoạt">
        <p>
          Bước dịch chạy qua máy chủ nên bạn <strong className="text-ink">không
          cần đăng ký tài khoản hay lấy API key</strong> của bất kỳ dịch vụ nào.
          Máy mới đã có sẵn Vox dùng thử.
        </p>
        <div className="space-y-4 mt-4">
          <Step n="1" title="Mua Vox">
            <p>
              Vào <Link to="/mua" className="text-primary hover:underline">trang mua</Link>,
              chọn gói hoặc nhập số tiền bạn muốn.
            </p>
          </Step>
          <Step n="2" title="Thanh toán qua PayOS">
            <p>
              Quét mã QR bằng app ngân hàng, hoặc mở trang thanh toán PayOS để
              trả bằng thẻ ATM, Visa/Mastercard hay ví điện tử.{' '}
              <strong className="text-ink">Hệ thống tự khớp đơn</strong> — không
              cần ghi nội dung gì.
            </p>
          </Step>
          <Step n="3" title="Nhận mã kích hoạt">
            <p>
              Vài giây sau khi thanh toán xong, mã dạng{' '}
              <code className="font-mono">VOX-XXXX-XXXX-XXXX</code> hiện ngay
              trên màn hình (và gửi vào email nếu bạn có điền).
            </p>
          </Step>
          <Step n="4" title="Kích hoạt trong ứng dụng">
            <p>
              Mở VoxDub.exe → mục <strong className="text-ink">Tài khoản</strong> →
              dán mã → bấm <strong className="text-ink">Kích hoạt</strong>.
            </p>
          </Step>
        </div>
        <div className="bg-warn/10 border border-warn/25 rounded-xl px-4 py-3 mt-4">
          <p className="text-xs text-warn leading-relaxed">
            Mỗi mã chỉ kích hoạt được một lần trên một máy. Vox gắn với chiếc
            máy đó chứ không gắn với tài khoản, nên cài lại ứng dụng hay xóa
            cấu hình đều không mất Vox.
          </p>
        </div>
      </Section>

      <Section title="Bước 5 — Chạy thử một video">
        <div className="space-y-2">
          <p>1. Mở VoxDub.exe, vào <strong className="text-ink">Tạo dự án</strong>.</p>
          <p>2. Dán link video, chọn ngôn ngữ gốc và giọng đọc.</p>
          <p>3. Bấm chạy. Lần đầu ứng dụng tự tải mô hình nhận dạng giọng nói
             (khoảng 1,5 GB, chỉ một lần).</p>
        </div>
        <p className="text-ink-muted text-xs">
          Video kết quả nằm trong thư mục <code>output</code> cạnh VoxDub.exe.
        </p>
      </Section>

      <Section title="Cài thêm khi cần">
        <div className="space-y-3">
          <div>
            <p className="text-ink font-medium">Tải video Douyin</p>
            <p>
              Đúp chuột <strong className="text-ink">Cai dat tinh nang Douyin.bat</strong>{' '}
              (khoảng 210 MB). YouTube và link trực tiếp không cần bước này.
            </p>
          </div>
          <div>
            <p className="text-ink font-medium">Nhận dạng tiếng Trung chính xác hơn</p>
            <p>
              Đúp chuột <strong className="text-ink">Cai dat ASR tieng Trung (Paraformer).bat</strong>{' '}
              (khoảng 520 MB). Video tiếng Trung sẽ được nghe chép chính xác hơn
              rõ rệt; ngôn ngữ khác vẫn dùng Whisper như cũ.
            </p>
          </div>
          <div>
            <p className="text-ink font-medium">Giọng đọc của chính bạn</p>
            <p>
              Thu một tệp WAV dài 5–10 giây (rõ, không nhạc nền) kèm tệp{' '}
              <code>.txt</code> cùng tên chứa đúng nội dung câu nói, rồi thêm
              vào trang Giọng đọc AI.
            </p>
          </div>
        </div>
      </Section>

      <Section title="Lỗi thường gặp">
        <div className="space-y-3">
          {[
            ['ffmpeg không nhận sau khi cài',
             'Đóng mở lại PowerShell và ứng dụng. Hoặc chép ffmpeg.exe và ffprobe.exe vào cạnh VoxDub.exe.'],
            ['App báo hết Vox',
             'Mở trang Tài khoản để nạp thêm, rồi chạy tiếp dự án đang dở — phần đã dịch xong không bị tính tiền lại.'],
            ['Mã báo "đã dùng trên máy khác"',
             'Mỗi mã chỉ dùng cho một máy. Nếu bạn chưa từng dùng mã này, liên hệ hỗ trợ kèm mã đơn hàng.'],
            ['Không kết nối được máy chủ',
             'Kiểm tra mạng. Các bước chạy trên máy (nghe chép, giọng đọc, xuất video) vẫn dùng bình thường.'],
            ['Chạy chậm, không dùng card đồ họa',
             'Cần card NVIDIA và driver mới. Gõ nvidia-smi trong PowerShell để kiểm tra.'],
            ['Antivirus chặn VoxDub.exe',
             'Thêm thư mục VoxDub vào danh sách loại trừ. Tệp đóng gói bằng PyInstaller hay bị nhận nhầm.'],
          ].map(([q, a]) => (
            <div key={q}>
              <p className="text-ink font-medium">{q}</p>
              <p>{a}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}
