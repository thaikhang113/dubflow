"""Design token — nguồn sự thật DUY NHẤT về màu, khoảng cách và bo góc.

Mọi file giao diện đều lấy màu từ đây. Cấm viết mã màu hex ở nơi khác
(bài kiểm thử `tests/test_ui_tokens.py` sẽ báo lỗi).

Giao diện TỐI (dark theme) — phong cách Linear/Vercel/GitHub dark:
nền than đậm, thẻ xám tối, accent chàm #6366f1, viền mảnh tinh tế.
"""
from __future__ import annotations

# -- Nền --------------------------------------------------------------
BG_APP          = "#0e0e14"   # nền cửa sổ — than đen tím nhẹ
BG_SIDEBAR      = "#16161e"   # thanh bên — tối hơn panel một chút
BG_MAIN         = "#0e0e14"   # vùng nội dung
BG_PANEL        = "#1a1a24"   # thẻ / khung nhóm
BG_PANEL_HOVER  = "#22222e"   # hover nhẹ — xanh tint tối
BG_INPUT        = "#1e1e2a"   # ô nhập

# Nền phụ trợ (dẫn xuất, dùng trong bảng kiểu QSS)
BG_INPUT_DISABLED = "#16161e"
BG_BUTTON         = "#20202c"  # nút mặc định
BG_BUTTON_PRESSED = "#2a2a48"  # nhấn → indigo tint tối
BG_VIDEO          = "#0d0d14"  # sân khấu video — GIỮ TỐI (letterbox)
BG_SELECTED       = "#2a2a48"  # nav item đang chọn — indigo tint tối
BG_SELECTED_SOFT  = "#1e1e38"  # selected nhạt hơn (chip, badge, hover nhẹ)

# -- Viền -------------------------------------------------------------
BORDER_SUBTLE   = "#252534"   # viền rất nhạt — phân tách nhẹ
BORDER_DEFAULT  = "#32324a"   # viền rõ hơn một chút
BORDER_ACTIVE   = "#6366f1"
BORDER_BUTTON   = "#32324a"   # viền nút — theo BORDER_DEFAULT
BORDER_DANGER   = "#5a1f1f"
BORDER_UPLOAD   = "#3a3a6a"

# -- Màu chính --------------------------------------------------------
PRIMARY         = "#6366f1"
PRIMARY_HOVER   = "#7577f3"   # sáng hơn một chút — trên nền tối đọc là hover
PRIMARY_DARK    = "#4f46e5"
PRIMARY_GRAD_B  = "#8b5cf6"   # điểm cuối dải chuyển sắc của nút chính
PRIMARY_GRAD_B_HOVER = "#7c4ff0"
PRIMARY_DISABLED_BG  = "#2a2a48"

# -- Màu nhấn ---------------------------------------------------------
ACCENT_BLUE     = "#4f6ef7"
ACCENT_PURPLE   = "#8b5cf6"
ACCENT_PURPLE_HOVER = "#9b6ef8"

# -- Chữ --------------------------------------------------------------
TEXT_PRIMARY    = "#e8e8f0"   # trắng xanh nhẹ — dễ đọc trên nền tối
TEXT_SECONDARY  = "#9090a8"   # xám tím vừa
TEXT_MUTED      = "#606078"   # xám tối — hint, meta
TEXT_DISABLED   = "#3e3e54"
TEXT_ON_ACCENT  = "#ffffff"

# -- Trạng thái -------------------------------------------------------
SUCCESS         = "#22c55e"   # xanh lá sáng hơn — đọc tốt trên nền tối
WARNING         = "#f59e0b"
DANGER          = "#f87171"   # đỏ sáng hơn — đọc tốt trên nền tối
PROCESSING      = "#6366f1"

# Nền huy hiệu (tối — chữ dùng màu trạng thái sáng)
SUCCESS_BG      = "#0d2a18"
WARNING_BG      = "#2a1e08"
DANGER_BG       = "#2a0d0d"
PROCESSING_BG   = "#1a1a38"
NEUTRAL_BG      = "#1a1a24"
PURPLE_BG       = "#1e1430"

# -- Dải thời gian ----------------------------------------------------
WAVEFORM         = "#6366f1"
WAVEFORM_LIGHT   = "#4a4c9a"
PLAYHEAD         = "#ef4444"   # đỏ, lấy mẫu từ ảnh tham chiếu
SUB_BLOCK_BG     = "#2a200a"
SUB_BLOCK_BORDER = "#a07820"
SUB_BLOCK_TEXT   = "#d4a840"
RULER_TEXT       = "#606078"

# Track đa kênh của timeline (theo ảnh tham chiếu)
TRACK_ORIGINAL      = "#8b5cf6"   # Âm thanh gốc (tím)
TRACK_ORIGINAL_BG   = "#1e1430"
TRACK_VOICE         = "#22c55e"   # Giọng đọc AI (xanh lá)
TRACK_VOICE_BG      = "#0d2018"
TRACK_MUSIC         = "#ec4899"   # Nhạc nền (hồng)
TRACK_MUSIC_BG      = "#2a0d1e"
TRACK_VIDEO_BG      = "#14141e"   # dải khung hình video
TRACK_LABEL_BG      = "#16161e"   # cột nhãn trái của timeline
TRACK_LABEL_BORDER  = "#252534"

# -- Khung xem trước kiểu phụ đề --------------------------------------
# Canvas xem trước hiển thị KHUNG HÌNH VIDEO nên giữ nền tối.
PREVIEW_CANVAS_BG   = "#141517"   # nền khung xem trước
PREVIEW_GUIDE       = "#3f6fb5"   # đường canh vị trí chữ
PREVIEW_BLUR_EDGE   = "#c2913a"   # viền vùng che
PREVIEW_EMPTY_BG    = "#1a1a24"   # nền khi chưa lấy được khung hình
PREVIEW_EMPTY_TEXT  = "#606078"
LOG_BG              = "#12121a"   # nền khung nhật ký

# -- Màu mặc định của chữ phụ đề ghi lên video -------------------------
# Đây là màu của nội dung xuất ra, không phải màu giao diện, nhưng vẫn để ở
# đây vì mọi mã màu trong dự án đều phải tập trung một chỗ.
SUBTITLE_TEXT_DEFAULT      = "#FFFFFF"
SUBTITLE_OUTLINE_DEFAULT   = "#000000"
SUBTITLE_HIGHLIGHT_DEFAULT = "#FFD54A"
SUBTITLE_BOXFILL_DEFAULT   = "#000000"   # khối nền mờ sau chữ

# -- Thanh cuộn và rãnh trượt -----------------------------------------
STEP_DONE_BG        = "#6366f1"   # vòng tròn bước đã xong
STEP_UPCOMING_BG    = "#22222e"   # vòng tròn bước chưa tới
STEP_UPCOMING_TEXT  = "#606078"

TRACK_BG        = "#22222e"
SCROLL_HANDLE_HOVER = "#44445a"
BRAND_LOGO_BG   = "#1a1a38"

# -- Thẻ giọng đọc & chip lọc -----------------------------------------
CHIP_BG            = "#1a1a24"   # nền chip lọc (thường)
CHIP_BG_ACTIVE     = "#1a1a38"   # nền chip đang chọn
CHIP_BORDER_ACTIVE = "#6366f1"   # viền chip đang chọn (= PRIMARY)
VOICE_SELECTED_BG  = "#1a1a38"   # nền thẻ giọng đang chọn
SECTION_LABEL      = "#606078"   # chữ CÔNG CỤ / HỆ THỐNG trong thanh bên

# Cặp màu gradient cho vòng tròn chữ cái đầu (avatar giọng đọc).
# Chọn cặp theo tên giọng bằng hàm băm ổn định để mỗi giọng luôn một màu.
AVATAR_GRADIENTS = (
    ("#6366f1", "#8b5cf6"),
    ("#ec4899", "#8b5cf6"),
    ("#3b82f6", "#6366f1"),
    ("#22c55e", "#0ea5a4"),
    ("#f59e0b", "#ef4444"),
    ("#8b5cf6", "#ec4899"),
)

# -- Màu bán trong suốt dùng trong QSS (Qt nhận alpha 0..255) ----------
NAV_SEL_GRAD_A  = "rgba(99,102,241,45)"    # mục đang chọn, phía trái (pill nhạt — tối hơn trên dark)
NAV_SEL_GRAD_B  = "rgba(99,102,241,35)"    # mục đang chọn, phía phải
NAV_HOVER_BG    = "rgba(99,102,241,28)"    # hover — indigo tint ~11% trên nền tối
MODAL_OVERLAY   = "rgba(0,0,0,180)"        # overlay tối hơn trên dark theme
DURATION_BADGE_BG = "rgba(0,0,0,200)"      # đè lên thumbnail — giữ tối
UPLOAD_GRAD_A   = "rgba(99,102,241,22)"    # nền thẻ tải lên, chàm ~9%
UPLOAD_GRAD_B   = "rgba(139,92,246,22)"    # nền thẻ tải lên, tím ~9%
DRAG_ACTIVE_BG  = "rgba(99,102,241,40)"    # khoảng 0,16 alpha
PLAYER_BAR_BG   = "rgba(22,22,30,230)"     # thanh điều khiển tối mờ
SUBTITLE_BOX_BG = "rgba(0,0,0,140)"        # đè lên video — giữ tối

# -- Bo góc -----------------------------------------------------------
RADIUS_SM = 6
RADIUS_MD = 9
RADIUS_LG = 12
RADIUS_XL = 16

# -- Khoảng cách (lưới 4px) -------------------------------------------
SP_1, SP_2, SP_3, SP_4, SP_5, SP_6, SP_8 = 4, 8, 12, 16, 20, 24, 32

# -- Kiểu chữ ---------------------------------------------------------
FONT_STACK = '"Segoe UI Variable", "Segoe UI", Arial, sans-serif'
FONT_MONO = '"Consolas", "Cascadia Mono", monospace'
FS_PAGE_TITLE   = 25   # tiêu đề trang
FS_SECTION      = 17   # tiêu đề mục
FS_CARD_TITLE   = 14
FS_BODY         = 13
FS_LABEL        = 12
FS_META         = 11
FS_BADGE        = 10

# -- Kích thước cố định -----------------------------------------------
SIDEBAR_W        = 220   # co xuống 200 khi cửa sổ dưới 1440, còn 64 khi dưới 1024
SIDEBAR_W_COMPACT = 200
SIDEBAR_W_ICON   = 64
NAV_ITEM_H       = 40
HEADER_H         = 72
CARD_MIN_W       = 240

# -- Đổ bóng (Qt dùng QGraphicsDropShadowEffect) ----------------------
SHADOW_BLUR   = 24
SHADOW_Y      = 8
SHADOW_ALPHA  = 22      # bóng nhẹ trên nền sáng, tương đương rgba(0,0,0,.09)


def rgba(hex_color: str, alpha: float) -> str:
    """Đổi mã hex '#rrggbb' thành chuỗi 'rgba(r,g,b,a)' dùng trong QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"
