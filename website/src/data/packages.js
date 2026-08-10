/**
 * Bullet tính năng cho từng gói — phần TĨNH hiển thị trên website.
 *
 * Giá/vox/bonus KHÔNG nằm ở đây — luôn lấy từ API (`credit.packages` phía
 * server) để không bao giờ lệch giá. File này chỉ map package id → mô tả,
 * còn các con số ước tính được TÍNH từ totalVox lúc render.
 *
 * Quy đổi (khớp giá server): 12 Vox/câu khi bật dịch tự động (mức phổ biến),
 * một phút video ≈ 10 câu thoại, một video ngắn điển hình ≈ 10 phút.
 */

const VOX_PER_SEGMENT = 12 // 10 cơ bản + 2 dịch tự động
const SEGMENTS_PER_MINUTE = 10
const MINUTES_PER_VIDEO = 10

/** Ước tính năng lực từ tổng Vox (vox + bonus) — trả các con số đã làm tròn. */
export function estimateCapacity(totalVox) {
  const segments = Math.floor(totalVox / VOX_PER_SEGMENT)
  const minutes = Math.floor(segments / SEGMENTS_PER_MINUTE)
  const videos = Math.max(1, Math.floor(minutes / MINUTES_PER_VIDEO))
  return { segments, minutes, videos }
}

/** Mô tả + perks theo package id. `fallback` dùng cho id lạ (đổi gói phía server). */
export const PACKAGE_DETAILS = {
  mini: {
    tagline: 'Mốc chuẩn 1.000 Vox = 10.000đ — thử ngay không lăn tăn',
    perks: [
      'Đủ dùng thử trọn một video ngắn',
      'Vox không hết hạn, dùng dần thoải mái',
      'Nhận mã kích hoạt ngay sau khi thanh toán',
    ],
  },
  starter: {
    tagline: 'Cho người mới bắt đầu ra video đều tay',
    perks: [
      'Tặng thêm 5% Vox so với mua lẻ',
      'Vox không hết hạn, dùng dần thoải mái',
      'Dịch tự động qua máy chủ VoxDub',
      'Tạo tiêu đề + mô tả đăng bài',
    ],
  },
  standard: {
    tagline: 'Lựa chọn của đa số — đủ cho cả tháng ra video',
    perks: [
      'Tặng thêm 10% Vox — mức hời rõ rệt',
      'Vox không hết hạn, dùng dần thoải mái',
      'Dịch tự động qua máy chủ VoxDub',
      'Tạo tiêu đề + mô tả đăng bài',
      'Đổi máy được hỗ trợ chuyển Vox',
    ],
  },
  pro: {
    tagline: 'Cho kênh đăng đều mỗi ngày',
    perks: [
      'Tặng thêm 15% Vox',
      'Vox không hết hạn, dùng dần thoải mái',
      'Dịch tự động qua máy chủ VoxDub',
      'Tạo tiêu đề + mô tả đăng bài',
      'Đổi máy được hỗ trợ chuyển Vox',
      'Chạy hàng loạt nhiều video liên tục',
    ],
  },
  studio: {
    tagline: 'Cho studio vận hành nhiều kênh',
    perks: [
      'Tặng thêm 20% Vox — mức hời cao nhất',
      'Vox không hết hạn, dùng dần thoải mái',
      'Dịch tự động qua máy chủ VoxDub',
      'Tạo tiêu đề + mô tả đăng bài',
      'Đổi máy được hỗ trợ chuyển Vox',
      'Chạy hàng loạt nhiều video liên tục',
      'Hỗ trợ ưu tiên qua Zalo/email',
    ],
  },
  fallback: {
    tagline: 'Nạp Vox dùng cho mọi tính năng của VoxDub',
    perks: [
      'Vox không hết hạn, dùng dần thoải mái',
      'Dịch tự động qua máy chủ VoxDub',
      'Nhận mã kích hoạt ngay sau khi thanh toán',
    ],
  },
}

export function packageDetails(id) {
  return PACKAGE_DETAILS[id] || PACKAGE_DETAILS.fallback
}
