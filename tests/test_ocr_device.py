from autodub.media.ocr_worker import choose_ocr_device


def test_ocr_device_auto_uses_gpu_when_paddle_cuda_is_ready():
    assert choose_ocr_device("auto", True) == "gpu:0"


def test_ocr_device_auto_falls_back_to_cpu():
    assert choose_ocr_device("auto", False) == "cpu"


def test_ocr_device_cpu_override_wins():
    assert choose_ocr_device("cpu", True) == "cpu"
