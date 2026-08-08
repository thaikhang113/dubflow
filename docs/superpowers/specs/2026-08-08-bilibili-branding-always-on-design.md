# Bilibili Branding Always-On Design

## Goal

Mọi video đi qua wrapper Bilibili phải che khối logo/uploader gốc và chèn logo
được duyệt trước khi organize hoặc gửi kết quả.

## Behavior

- Branding luôn bật cho job Bilibili; không phụ thuộc `BILIBILI_BRANDING`.
- `single_job_brand.py` xử lý `final_video_vi.mp4` sau quality gate.
- Vùng `bilibili_top_left_block` được blur và thay bằng logo trong
  `brand-assets.json`.
- Intro và outro vẫn do `BILIBILI_BRAND_INCLUDE_INTRO` và
  `BILIBILI_BRAND_INCLUDE_OUTRO` điều khiển, mặc định tắt.
- Pipeline con luôn chạy với `ORGANIZE_OUTPUT=0 AUTO_TELEGRAM_RESULT=0`.
- Chỉ video đã brand mới được organize, sao chép ra output chung hoặc gửi Telegram.
- Thiếu script, asset, video cuối hoặc branding thất bại phải fail closed.
- Giữ `bilibili_branding_proof.json` làm bằng chứng.
- Không thêm hiệu ứng lật gương.

## Implementation

Chỉ sửa `skills/bilibili-vietnamese-dubber/run.sh`. Xóa nhánh chạy unbranded và
validation cho cờ `BILIBILI_BRANDING`; giữ validation intro/outro. Tái sử dụng
`single_job_brand.py` và asset hiện có, không thêm dependency hay abstraction.

## Testing

Thêm static regression test trong `test_url_normalization.py` xác nhận:

- wrapper không còn default branding tắt;
- pipeline con luôn chặn organize/Telegram;
- branding script luôn được gọi;
- hand-off chỉ xảy ra sau branding;
- intro/outro vẫn được truyền vào branding script.

Chạy test Bilibili, test single-job branding, `bash -n`, `compileall` và
`git diff --check`.
