import { useState } from 'react'
import { Link } from 'react-router-dom'

const GROUPS = [
  {
    group: 'Về Vox và thanh toán',
    items: [
      ['Vox là gì?',
       'Vox là đơn vị tính phí của VoxDub. Mỗi câu thoại trong video tốn 10 '
       + 'Vox (12 nếu bật dịch tự động qua máy chủ) — đã gồm trọn nghe chép, '
       + 'giọng đọc, phụ đề và dựng video.'],
      ['Vox có hết hạn không?',
       'Không. Vox nằm trong ví của máy bạn cho tới khi dùng hết.'],
      ['Một video tốn bao nhiêu Vox?',
       'Bằng số câu thoại nhân 10 Vox (12 nếu bật dịch tự động), cộng 20 Vox '
       + 'nếu tạo tiêu đề + mô tả đăng bài. Video 10 phút thường có 150–300 '
       + 'câu. Giá chốt ngay sau bước nghe chép — ứng dụng báo đúng tổng số '
       + 'trước khi trừ ví.'],
      ['Có gói thuê bao hàng tháng không?',
       'Không. Không thuê bao, không tự động gia hạn, không lưu thẻ. Mua một '
       + 'lần dùng dần.'],
      ['Thanh toán bằng cách nào?',
       'Qua PayOS: quét QR bằng app ngân hàng bất kỳ, thẻ ATM, Visa/Mastercard '
       + 'hoặc ví điện tử. Hệ thống tự khớp đơn — không cần ghi nội dung gì.'],
      ['Thanh toán xong bao lâu thì nhận mã?',
       'Thường vài giây — PayOS báo về ngay khi giao dịch thành công. Trang '
       + 'thanh toán tự cập nhật, bạn không cần tải lại.'],
      ['Thanh toán xong mà chưa thấy mã?',
       'Hiếm khi xảy ra. Nếu sau 5 phút vẫn chưa thấy, liên hệ hỗ trợ kèm mã '
       + 'đơn hàng (dạng VOXxxxxxx) và thời điểm thanh toán — chúng tôi cấp mã '
       + 'thủ công ngay.'],
    ],
  },
  {
    group: 'Về mã kích hoạt',
    items: [
      ['Một mã dùng được cho mấy máy?',
       'Đúng một máy, không có ngoại lệ. Đây là ràng buộc ở tầng dữ liệu chứ '
       + 'không phải quy ước — mã đã kích hoạt thì mọi lần nhập lại ở máy khác '
       + 'đều bị từ chối.'],
      ['Tôi lỡ đóng tab trước khi chép mã',
       'Mở lại trang "Đơn hàng của tôi" trên chính trình duyệt đó — mã vẫn '
       + 'còn. Nếu bạn có điền email lúc mua thì mã cũng đã được gửi vào hộp thư.'],
      ['Tôi mở link đơn hàng ở máy khác mà không thấy mã',
       'Đúng như thiết kế. Mã chỉ hiện trên trình duyệt đã tạo đơn, vì mã đơn '
       + 'hàng ngắn và có thể bị dò. Hãy mở lại tab cũ hoặc dùng chức năng gửi '
       + 'mã vào email.'],
      ['Tôi mua nhiều mã cùng lúc được không?',
       'Được. Mỗi đơn cho ra một mã. Bạn có thể nhập nhiều mã vào cùng một máy '
       + '— số Vox cộng dồn.'],
    ],
  },
  {
    group: 'Về máy và ứng dụng',
    items: [
      ['Vì sao không cần đăng ký tài khoản?',
       'Vì ví Vox gắn thẳng với chiếc máy của bạn, xác định bằng một mã sinh '
       + 'từ phần cứng và hệ điều hành. Không có mật khẩu để quên, không có '
       + 'email để xác thực.'],
      ['Cài lại ứng dụng có mất Vox không?',
       'Không. Mã máy không đổi khi bạn cài lại ứng dụng, xóa cấu hình hay đổi '
       + 'thư mục.'],
      ['Cài lại Windows hoặc đổi máy thì sao?',
       'Mã máy sẽ đổi. Liên hệ hỗ trợ kèm mã máy cũ và mới (xem ở trang Tài '
       + 'khoản trong ứng dụng), chúng tôi chuyển số Vox còn lại sang máy mới.'],
      ['Dùng được trên mấy máy cùng lúc?',
       'Mỗi máy có ví riêng. Muốn dùng hai máy thì mua Vox cho từng máy.'],
      ['Có bản macOS hoặc Linux không?',
       'Chưa có. Ứng dụng dùng một số thành phần chỉ chạy trên Windows.'],
      ['Không có mạng thì dùng được không?',
       'Nghe chép, giọng đọc, phụ đề và xuất video vẫn chạy bình thường. Riêng '
       + 'bước dịch cần mạng — nó sẽ dừng lại và báo rõ, phần đã dịch xong '
       + 'không mất.'],
    ],
  },
  {
    group: 'Về chất lượng',
    items: [
      ['Bản dịch có tự nhiên không?',
       'Máy chủ đọc hiểu toàn bộ video trước khi dịch: chủ đề, nhân vật, cách '
       + 'xưng hô và thuật ngữ được giữ nhất quán. Bạn còn có thể tự điền ngữ '
       + 'cảnh ở trang Dịch thuật để bản dịch bám đúng văn phong kênh mình.'],
      ['Giọng đọc nghe có giống người thật không?',
       'VieNeu là bộ giọng tiếng Việt chạy trên máy, hơn 100 giọng nam nữ ba '
       + 'miền. Bạn cũng có thể nhân bản giọng của chính mình từ một đoạn ghi '
       + 'âm 10 giây.'],
      ['Nhạc nền có bị mất không?',
       'Không. Demucs tách riêng giọng nói khỏi nhạc, rồi ghép giọng Việt vào '
       + 'đúng chỗ — nhạc, tiếng động và hiệu ứng gốc còn nguyên.'],
      ['Câu dịch dài hơn câu gốc thì sao?',
       'Máy chủ canh sẵn số ký tự vừa với khung thời gian từng câu. Nếu vẫn '
       + 'chật, ứng dụng dồn nhẹ các câu sau vào khoảng lặng thay vì đọc nhanh '
       + 'lên. Bạn cũng có thể giảm tốc độ video một chút cho thoáng.'],
    ],
  },
]

function Item({ q, a }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-border-subtle last:border-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left py-3.5 flex items-start justify-between gap-4"
        aria-expanded={open}
      >
        <span className="text-sm font-medium">{q}</span>
        <span
          className={`text-ink-muted shrink-0 mt-0.5 transition-transform ${
            open ? 'rotate-45' : ''
          }`}
        >
          +
        </span>
      </button>
      {open && (
        <p className="text-sm text-ink-soft pb-4 pr-8 leading-relaxed">{a}</p>
      )}
    </div>
  )
}

export default function Faq() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-14">
      <h1 className="text-3xl font-bold">Câu hỏi thường gặp</h1>

      <div className="mt-8 space-y-5">
        {GROUPS.map((g) => (
          <div key={g.group} className="card px-5 py-2">
            <p className="text-xs font-semibold text-primary uppercase tracking-wide pt-3 pb-1">
              {g.group}
            </p>
            {g.items.map(([q, a]) => <Item key={q} q={q} a={a} />)}
          </div>
        ))}
      </div>

      <div className="card p-6 mt-5 text-center">
        <p className="text-sm text-ink-soft">Không tìm thấy câu trả lời?</p>
        <Link to="/lien-he" className="btn-ghost mt-3 inline-flex">
          Liên hệ hỗ trợ
        </Link>
      </div>
    </div>
  )
}
