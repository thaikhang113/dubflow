import sys

from autodub.gpu import GPUInfo, detect_gpu


def _runner(responses):
    def run(command):
        key = command[0]
        return responses.get(key, (1, ""))
    return run


def test_detects_amd_linux_with_rocm():
    info = detect_gpu(
        platform_name="linux",
        command_runner=_runner({
            "lspci": (0, "03:00.0 VGA compatible controller: AMD Radeon RX 6600"),
            "rocminfo": (0, "ROCk module"),
        }),
    )

    assert info == GPUInfo("amd", "03:00.0 VGA compatible controller: AMD Radeon RX 6600",
                           "rocm", True, "ROCm probe")


def test_detects_amd_windows_with_directml():
    info = detect_gpu(
        platform_name="win32",
        command_runner=_runner({
            "powershell": (0, "AMD Radeon RX 6600"),
            sys.executable: (0, "True"),
        }),
    )

    assert info.vendor == "amd"
    assert info.compute_backend == "directml"
    assert info.compute_available is True


def test_amd_without_runtime_reports_cpu_fallback():
    info = detect_gpu(
        platform_name="linux",
        command_runner=_runner({
            "lspci": (0, "AMD Radeon RX 6600"),
            "rocminfo": (1, ""),
        }),
    )

    assert info.label == "AMD Radeon RX 6600 (CPU fallback)"
    assert "unavailable" in info.reason


def test_unknown_machine_is_cpu():
    info = detect_gpu(
        platform_name="linux",
        command_runner=_runner({"lspci": (1, "")}),
    )

    assert info.compute_available is False
    assert info.compute_backend == "cpu"

def test_windows_skips_virtual_display_adapter_when_real_gpu_is_present():
    info = detect_gpu(
        platform_name="win32",
        command_runner=_runner({
            "powershell": (
                0,
                "DeskIn Virtual Display Adapter\n"
                "NVIDIA GeForce RTX 3050 Ti Laptop GPU",
            ),
            "nvidia-smi": (0, "GPU 0: NVIDIA GeForce RTX 3050 Ti Laptop GPU"),
        }),
    )

    assert info.vendor == "nvidia"
    assert info.name == "NVIDIA GeForce RTX 3050 Ti Laptop GPU"
    assert info.compute_backend == "cuda"
    assert info.compute_available is True
