import io
import ipaddress
from pathlib import Path
import socket
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, UnidentifiedImageError

MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_DIMENSION = 4096


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _public_host(hostname: str, resolver=socket.getaddrinfo) -> None:
    try:
        addresses = {
            item[4][0]
            for item in resolver(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError("logo host cannot be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ValueError("logo URL must use a public host")


def save_logo(data: bytes, target: Path) -> dict:
    if not data or len(data) > MAX_LOGO_BYTES:
        raise ValueError("logo must be between 1 byte and 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("logo must be PNG, JPEG, or WebP")
            if (
                image.width < 1
                or image.height < 1
                or image.width > MAX_LOGO_DIMENSION
                or image.height > MAX_LOGO_DIMENSION
            ):
                raise ValueError("logo dimensions must be between 1 and 4096 pixels")
            rendered = image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("logo file is not a valid image") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".branding-logo-",
        suffix=".png",
        dir=target.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        rendered.save(temporary_path, "PNG", optimize=True)
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {"width": rendered.width, "height": rendered.height}


def download_logo(url: str, target: Path, opener=None, resolver=socket.getaddrinfo) -> dict:
    if len(str(url or "")) > 2048:
        raise ValueError("logo URL is too long")
    try:
        parsed = urlsplit(str(url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid logo URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        raise ValueError("logo URL must be public HTTPS without credentials")
    _public_host(parsed.hostname, resolver)
    client = opener or build_opener(_NoRedirect)
    request = Request(url, headers={"User-Agent": "AutoVietsub/1"})
    try:
        with client.open(request, timeout=20) as response:
            if getattr(response, "status", 200) != 200:
                raise ValueError("logo download failed")
            content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0]
            if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise ValueError("logo URL must return PNG, JPEG, or WebP")
            chunks = []
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_LOGO_BYTES:
                    raise ValueError("logo download exceeds 5 MB")
                chunks.append(chunk)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("logo download failed") from exc
    return save_logo(b"".join(chunks), target)
