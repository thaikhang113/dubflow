import io
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from web_tool.branding import download_logo, save_logo


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(output, "PNG")
    return output.getvalue()


class BrandingTests(unittest.TestCase):
    def test_logo_is_validated_and_saved_as_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "branding-logo.png"
            result = save_logo(png_bytes(), target)
            self.assertEqual({"width": 64, "height": 64}, result)
            with Image.open(target) as image:
                self.assertEqual("PNG", image.format)
            with self.assertRaises(ValueError):
                save_logo(b"not-an-image", target)

    def test_logo_url_allows_https_public_hosts_only(self):
        response = Mock()
        response.status = 200
        response.headers = {"Content-Type": "image/png"}
        response.read.side_effect = [png_bytes(), b""]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        resolver = Mock(
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "branding-logo.png"
            download_logo("https://images.example.com/logo.png", target, opener, resolver)
            self.assertTrue(target.is_file())
        for url in (
            "http://images.example.com/logo.png",
            "https://127.0.0.1/logo.png",
            "https://user:pass@images.example.com/logo.png",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                download_logo(url, Path("unused.png"), opener, resolver)


if __name__ == "__main__":
    unittest.main()
