"""Kết nối tới máy chủ dịch tùy chọn (backend trong ``control_server/``).

Máy chủ này là TÙY CHỌN. Không cấu hình ``VOXDUB_API_URL`` thì app chạy hoàn
toàn trên máy: nghe-chép bằng Whisper, đọc bằng VieNeu, còn bước dịch chuyển
sang dịch tay (app ghi sẵn lời nhắc ra ``TRANSLATE_PENDING.txt``).

Ai muốn dịch tự động thì tự dựng backend (xem ``control_server/README.md``)
rồi trỏ ``VOXDUB_API_URL`` về đó. Khi đã có máy chủ:

- App đăng ký thiết bị một lần để lấy token (``ensure_session``). Token cất
  trong kho khóa của hệ điều hành, hết hạn thì tự đăng ký lại.
- Mỗi lô mang ``job_id`` ổn định. Rớt mạng giữa chừng, app không biết request
  đã tới nơi hay chưa — gửi lại đúng ``job_id`` đó thì máy chủ trả kết quả cũ
  và KHÔNG trừ credit lần hai.

Nguyên tắc fail-closed: đã cấu hình máy chủ mà gọi không được thì dừng bước
dịch với lời báo rõ ràng, không âm thầm bỏ qua.
"""
from __future__ import annotations

import os
import threading
import uuid

from autodub.device_id import get_device_name, get_fingerprint
from autodub.utils import setup_logging

logger = setup_logging("autodub.saas")

ENV_KEY = "VOXDUB_API_URL"
#: Tên mục trong kho khóa hệ điều hành, nơi cất token thiết bị.
TOKEN_KEY = "VOXDUB_DEVICE_TOKEN"

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 300.0     # một lô dịch lớn có thể mất vài phút


class SaasError(Exception):
    """Máy chủ không trả về kết quả dùng được."""

    def __init__(self, message: str, code: str = "", status: int = 0,
                 retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        #: Giây máy chủ yêu cầu chờ trước khi thử lại (header ``Retry-After``),
        #: 0 nếu máy chủ không nói gì. Bước dịch dùng để giãn nhịp retry.
        self.retry_after = retry_after


class OfflineError(SaasError):
    """Không kết nối được máy chủ (mất mạng, máy chủ sập, sai địa chỉ)."""


class InsufficientCreditError(SaasError):
    """Hết Vox — người dùng cần nạp thêm trước khi chạy tiếp."""

    def __init__(self, message: str, balance: int = 0, required: int = 0) -> None:
        super().__init__(message, code="INSUFFICIENT_CREDIT", status=402)
        self.balance = balance
        self.required = required


class DeviceBlockedError(SaasError):
    """Thiết bị bị khóa từ phía quản trị."""


class MaintenanceError(SaasError):
    """Hệ thống đang bảo trì."""


def resolve_api_url() -> str:
    """Địa chỉ máy chủ dịch, hoặc chuỗi rỗng khi chạy thuần trên máy.

    Thứ tự: giá trị nhúng lúc build exe → biến môi trường ``VOXDUB_API_URL``
    (chỉ khi chạy từ mã nguồn). Rỗng = không có máy chủ, bước dịch tự chuyển
    sang dịch tay.
    """
    import sys

    from autodub_gui._embedded import VOXDUB_API_URL as embedded

    url = (embedded or "").strip()
    if not getattr(sys, "frozen", False):
        url = os.environ.get(ENV_KEY, "").strip() or url
    return url.rstrip("/")


def is_configured() -> bool:
    """True khi có máy chủ dịch để gọi."""
    return bool(resolve_api_url())


def new_job_id() -> str:
    """Khóa idempotency cho một lượt gọi."""
    return str(uuid.uuid4())


class SaasClient:
    """Máy khách HTTP tới máy chủ VoxDub. An toàn khi dùng từ nhiều luồng.

    Token được chia sẻ giữa các luồng nên mọi thao tác đọc/ghi token đều nằm
    trong khóa: hai luồng cùng gặp 401 chỉ được đăng ký lại MỘT lần, không
    phải hai (đăng ký lại hai lần sẽ cấp hai token và luồng kia dùng token đã
    bị thay).
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or resolve_api_url()).rstrip("/")
        self._token: str | None = None
        self._lock = threading.RLock()
        self._local = threading.local()
        self._device: dict = {}
        self._config: dict = {}

    # ------------------------------------------------------------ phiên --

    def _http(self):
        """Phiên requests RIÊNG cho từng luồng (giữ kết nối, đỡ bắt tay TLS).

        Bước dịch chạy tới 4 luồng trên cùng một client. ``requests.Session``
        không hứa an toàn nhiều luồng (pool kết nối và hộp cookie đều là state
        chung), mà bọc khóa quanh mỗi request thì 4 lô dịch thành tuần tự —
        mất đúng phần song song. Một session mỗi luồng chỉ tốn thêm một lần
        bắt tay TLS cho mỗi luồng trong cả lượt chạy.
        """
        session = getattr(self._local, "session", None)
        if session is None:
            import requests

            session = requests.Session()
            session.headers["User-Agent"] = f"VoxDub/{_app_version()} (Windows)"
            self._local.session = session
        return session

    def _load_token(self) -> str:
        """Token đã cất trong kho khóa hệ điều hành, hoặc chuỗi rỗng."""
        if self._token is not None:
            return self._token
        from autodub import keystore

        self._token = keystore.get_secret(TOKEN_KEY) or ""
        return self._token

    def _store_token(self, token: str) -> None:
        from autodub import keystore

        self._token = token
        # Kho khóa không dùng được (máy thiếu gói keyring) thì token chỉ sống
        # trong phiên này — mỗi lần mở app đăng ký lại, vẫn chạy đúng.
        keystore.set_secret(TOKEN_KEY, token)

    def forget_token(self) -> None:
        """Quên token hiện tại (dùng khi máy chủ báo token đã bị thu hồi)."""
        from autodub import keystore

        with self._lock:
            self._token = ""
            keystore.delete_secret(TOKEN_KEY)

    # ------------------------------------------------------- gọi HTTP ----

    def _request(self, method: str, path: str, *, json_body: dict | None = None,
                 auth: bool = True, timeout: float = _READ_TIMEOUT,
                 _retry_auth: bool = True) -> dict:
        """Một lượt gọi API. Ném :class:`SaasError` cho mọi lỗi.

        Gặp 401 thì đăng ký lại thiết bị đúng một lần rồi thử lại — token hết
        hạn là chuyện bình thường sau vài tuần, người dùng không cần biết.
        """
        if not self.base_url:
            raise OfflineError("Chưa cấu hình địa chỉ máy chủ VoxDub.")

        import requests

        headers = {}
        if auth:
            token = self._load_token() or self._register_device()
            headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}{path}"
        try:
            resp = self._http().request(
                method, url, json=json_body, headers=headers,
                timeout=(_CONNECT_TIMEOUT, timeout))
        except requests.exceptions.RequestException as e:
            raise OfflineError(
                "Không kết nối được máy chủ VoxDub. Kiểm tra mạng rồi thử lại."
            ) from e

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as e:
                raise SaasError("Máy chủ trả về dữ liệu không đọc được.") from e

        try:
            data = resp.json()
        except ValueError:
            data = {}
        code = str(data.get("code") or "")
        message = str(data.get("message") or f"Lỗi máy chủ (HTTP {resp.status_code})")

        if resp.status_code == 401 and auth and _retry_auth:
            # Token hết hạn hoặc bị thu hồi — đăng ký lại rồi thử lại đúng một lần.
            self.forget_token()
            return self._request(method, path, json_body=json_body, auth=auth,
                                 timeout=timeout, _retry_auth=False)
        if resp.status_code == 402:
            raise InsufficientCreditError(
                message, balance=int(data.get("balance") or 0),
                required=int(data.get("required") or 0))
        if code == "DEVICE_BLOCKED":
            raise DeviceBlockedError(message, code=code, status=resp.status_code)
        if code == "MAINTENANCE":
            raise MaintenanceError(message, code=code, status=resp.status_code)
        if resp.status_code == 429:
            raise SaasError(
                "Máy chủ đang bận (quá nhiều yêu cầu). Chờ một chút rồi thử lại.",
                code="RATE_LIMITED", status=429,
                retry_after=_retry_after_s(resp))
        raise SaasError(message, code=code, status=resp.status_code,
                        retry_after=_retry_after_s(resp))

    # ---------------------------------------------------------- thiết bị --

    def _register_device(self) -> str:
        """Đăng ký máy này và cất token. Trả về token."""
        with self._lock:
            # Một luồng khác có thể vừa đăng ký xong trong lúc ta chờ khóa.
            if self._token:
                return self._token
            data = self._request(
                "POST", "/v1/device/register", auth=False, timeout=30.0,
                json_body={
                    "fingerprint": get_fingerprint(),
                    "name": get_device_name(),
                    "appVersion": _app_version(),
                })
            self._store_token(str(data["token"]))
            self._device = data.get("device") or {}
            return self._token

    def ensure_session(self) -> dict:
        """Bảo đảm có token dùng được; trả về thông tin thiết bị + số dư.

        Gọi lúc khởi động app. Ném :class:`OfflineError` khi không kết nối
        được — người gọi quyết định hiện cảnh báo hay chặn hẳn.
        """
        if not self._load_token():
            self._register_device()
        data = self._request("GET", "/v1/device/me", timeout=30.0)
        self._device = data.get("device") or {}
        self._device["creditEnabled"] = bool(data.get("creditEnabled", True))
        return self._device

    @property
    def device(self) -> dict:
        """Thông tin thiết bị đã đọc gần nhất (có thể rỗng nếu chưa gọi)."""
        return dict(self._device)

    def balance(self) -> int:
        data = self._request("GET", "/v1/device/balance", timeout=30.0)
        balance = int(data.get("balance") or 0)
        self._device["balance"] = balance
        return balance

    def activate_key(self, code: str) -> dict:
        """Kích hoạt một mã. Trả về ``{vox, balanceAfter, alreadyActivated}``."""
        data = self._request("POST", "/v1/device/activate", timeout=30.0,
                             json_body={"code": str(code).strip()})
        self._device["balance"] = int(data.get("balanceAfter") or 0)
        return data

    def credit_history(self, page: int = 1, limit: int = 20) -> dict:
        return self._request(
            "GET", f"/v1/device/history?page={page}&limit={limit}", timeout=30.0)

    def estimate(self, sentences: int, *, auto_translate: bool = False,
                 metadata: bool = False) -> dict:
        """Giá của một video ``sentences`` segment, hỏi trước khi chạy.

        Cùng công thức với lúc tạo hold nên con số hiện cho người dùng ở bước
        xem trước khớp đúng số bị trừ. Trả về ``{"estimated", "balance",
        "enough"}`` — máy chủ không trả bảng chi tiết theo bước xử lý.
        """
        return self._request("POST", "/v1/device/estimate", timeout=30.0, json_body={
            "sentences": int(sentences),
            "autoTranslate": bool(auto_translate),
            "metadata": bool(metadata),
        })

    # ------------------------------------------------------ cấu hình app --

    def app_config(self, force: bool = False) -> dict:
        """Cấu hình máy chủ (bảo trì, phiên bản tối thiểu, bảng giá).

        Gọi lúc khởi động. Không kết nối được thì trả về dict rỗng — app vẫn
        mở lên được, chỉ dừng ở bước dịch (fail-closed đúng chỗ cần).
        """
        if self._config and not force:
            return self._config
        try:
            config = self._request("GET", "/v1/config/app", auth=False,
                                   timeout=15.0)
        except SaasError:
            config = {}
        with self._lock:
            self._config = config
        return config

    def _note_usage(self, data: dict) -> None:
        """Ghi số Vox vừa tiêu vào sổ chung của lượt dịch, và cập nhật số dư.

        Gọi sau MỌI lượt gọi AI thành công — báo cáo chất lượng cuối video
        lấy con số từ đây, và thanh Vox trên đầu app đọc ``device["balance"]``.
        Bước dịch gọi hàm này từ nhiều luồng nên phần ghi ``_device`` nằm trong
        khóa; ``USAGE.add`` đã tự khóa.
        """
        from autodub.text.translate_common import USAGE

        balance = int(data.get("balanceAfter") or 0)
        with self._lock:
            self._device["balance"] = balance
        USAGE.add(int(data.get("creditCharged") or 0), balance)

    # ------------------------------------------------------ hold (giữ chỗ) --

    def create_hold(self, hold_id: str, sentences: int,
                    video_duration_s: float = 0.0,
                    auto_translate: bool = True,
                    metadata: bool = True) -> dict:
        """Giữ chỗ Vox cho một lượt lồng tiếng — TRỪ ĐỦ GIÁ ngay tại đây.

        ``hold_id`` = run_id (hash nội dung transcript) nên gọi lại cùng
        video là idempotent — nhận về đúng hold cũ kèm khóa giải mã.

        Giá chốt từ số segment: ``auto_translate`` cộng thêm mỗi segment,
        ``metadata`` (tiêu đề + mô tả) là phụ phí trọn gói một lần. Sau bước
        này giá không đổi nữa, dùng nhiều hay ít lượt AI cũng vậy.
        Trả về ``{"hold": {..., "encKeyHex"}, "balance", "created"}``.
        Thiếu Vox → :class:`InsufficientCreditError`.
        """
        data = self._request("POST", "/v1/holds", timeout=30.0, json_body={
            "holdId": str(hold_id),
            "sentences": int(sentences),
            "videoDurationS": float(video_duration_s),
            "autoTranslate": bool(auto_translate),
            "metadata": bool(metadata),
        })
        self._device["balance"] = int(data.get("balance") or 0)
        return data

    def get_hold(self, hold_id: str) -> dict:
        """Trạng thái hold + khóa giải mã (khi còn active hoặc đã committed).

        Trả về ``{"hold": {...}, "balance"}``. Không tìm thấy → SaasError 404.
        """
        data = self._request("GET", f"/v1/holds/{hold_id}", timeout=30.0)
        self._device["balance"] = int(data.get("balance") or 0)
        return data

    def commit_hold(self, hold_id: str) -> dict:
        """Chốt hold lúc xuất video — mở khóa, KHÔNG động vào tiền.

        Giá đã trừ đủ lúc tạo hold nên bước này không hoàn cũng không truy
        thu. Idempotent — gọi lại trả kết quả cũ kèm ``encKeyHex``. Trả về
        ``{"committed", "usedVox", "chargedVox", "balance", "encKeyHex"}``.
        """
        data = self._request("POST", f"/v1/holds/{hold_id}/commit", timeout=60.0)
        balance = int(data.get("balance") or 0)
        self._device["balance"] = balance
        from autodub.text.translate_common import USAGE

        # Đồng bộ số dư lên thanh Vox (không cộng thêm usage — đã tích lũy
        # từng lượt trong lúc chạy rồi).
        USAGE.add(0, balance)
        return data

    # -------------------------------------------------------------- AI ---

    def translate(self, segments: list[dict], *, job_id: str, source_lang: str,
                  context: dict | None = None, cps_budget: float = 12.5,
                  prev_context: list[dict] | None = None,
                  hold_id: str | None = None) -> dict:
        """Dịch một lô câu.

        ``segments``: ``[{"id", "text", "duration", "max_chars"}]``.
        Trả về ``{"segments": [{"id", "text_vi"}], "creditCharged", "balanceAfter"}``.
        """
        payload = {
            "jobId": job_id,
            "sourceLang": source_lang,
            "cpsBudget": float(cps_budget),
            "segments": segments,
        }
        if context:
            payload["context"] = context
        if prev_context:
            payload["prevContext"] = prev_context
        if hold_id:
            payload["holdId"] = hold_id
        data = self._request("POST", "/v1/ai/translate", json_body=payload)
        self._note_usage(data)
        return data

    def analyze(self, lines: list[str], *, job_id: str, source_lang: str,
                video_title: str = "", hold_id: str | None = None) -> dict | None:
        """Phân tích ngữ cảnh video (lượt 0). Trả về dict hoặc None."""
        payload = {
            "jobId": job_id,
            "sourceLang": source_lang,
            "videoTitle": video_title[:300],
            "lines": lines,
        }
        if hold_id:
            payload["holdId"] = hold_id
        data = self._request("POST", "/v1/ai/analyze", timeout=120.0,
                             json_body=payload)
        self._note_usage(data)
        return data.get("analysis")

    def review(self, items: list[dict], *, job_id: str, source_lang: str,
               context: dict | None = None, cps_budget: float = 12.5,
               hold_id: str | None = None) -> list[dict]:
        """Rà soát các câu nghi vấn. Trả về danh sách câu ĐÃ SỬA (có thể rỗng)."""
        payload = {
            "jobId": job_id,
            "sourceLang": source_lang,
            "cpsBudget": float(cps_budget),
            "items": items,
        }
        if context:
            payload["context"] = context
        if hold_id:
            payload["holdId"] = hold_id
        data = self._request("POST", "/v1/ai/review", json_body=payload)
        self._note_usage(data)
        return data.get("segments") or []

    def generate_post(self, script_original: str, script_vi: str, *,
                      job_id: str, video_title: str = "",
                      hold_id: str | None = None) -> dict:
        """Viết tiêu đề, mô tả và hashtag. Trả về dict metadata."""
        payload = {
            "jobId": job_id,
            "scriptOriginal": script_original[:20000],
            "scriptVi": script_vi[:20000],
            "videoTitle": video_title[:300],
        }
        if hold_id:
            payload["holdId"] = hold_id
        data = self._request("POST", "/v1/ai/generate-post", timeout=180.0,
                             json_body=payload)
        self._note_usage(data)
        return data.get("metadata") or {}


def _retry_after_s(resp) -> float:
    """Header ``Retry-After`` dạng số giây, 0 nếu thiếu hoặc là mốc HTTP-date.

    Máy chủ VoxDub chỉ gửi dạng số giây; dạng ngày tháng bỏ qua cho gọn — bên
    gọi đã có giãn cách mặc định của riêng nó.
    """
    try:
        value = float((resp.headers.get("Retry-After") or "").strip())
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return max(0.0, min(60.0, value))


def _app_version() -> str:
    try:
        from autodub_gui.app import APP_VERSION

        return APP_VERSION
    except Exception:  # noqa: BLE001 — dùng từ CLI, không có GUI
        return "3.0.0"


# Máy khách dùng chung cho cả tiến trình: token, phiên HTTP và cấu hình chỉ
# nên tồn tại một bản. Dựng lười để nạp module không tốn gì.
_client: SaasClient | None = None
_client_lock = threading.Lock()


def get_client() -> SaasClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = SaasClient()
        return _client


def reset_client() -> None:
    """Vứt máy khách hiện tại (dùng sau khi đổi địa chỉ máy chủ trong dev)."""
    global _client
    with _client_lock:
        _client = None
