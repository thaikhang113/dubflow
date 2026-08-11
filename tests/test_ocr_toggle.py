from autodub.config import Settings
from autodub.pipeline import DubRequest, ocr_enabled_for_request


def test_request_ocr_toggle_overrides_global_setting():
    settings = Settings(ocr_enabled=True)

    assert ocr_enabled_for_request(settings, DubRequest()) is True
    assert ocr_enabled_for_request(settings, DubRequest(ocr_enabled=False)) is False
    assert ocr_enabled_for_request(
        Settings(ocr_enabled=False), DubRequest(ocr_enabled=True)
    ) is True


def test_manual_blur_regions_are_independent_from_ocr_toggle():
    region = {"x": 0.1, "y": 0.8, "w": 0.3, "h": 0.1, "source": "manual"}
    request = DubRequest(ocr_enabled=False, blur_regions=[region])

    assert request.blur_regions == [region]
