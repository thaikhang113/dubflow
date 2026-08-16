from types import SimpleNamespace

from autodub.hardware import HardwareProfile, detect_hardware, select_backends


def test_select_backends_prefers_amd_rocm_and_vsr():
    plan = select_backends(HardwareProfile(
        platform="linux",
        machine="x86_64",
        python="3.12",
        ram_gb=16,
        disk_free_gb=20,
        gpu_vendor="amd",
        gpu_name="AMD Radeon RX 6600",
        amd=True,
        rocm=True,
        vulkan=True,
    ))

    assert plan.ocr_backend == "deepseek-rocm"
    assert plan.vsr_backend == "video-subtitle-remover"


def test_select_backends_falls_back_on_small_machine():
    plan = select_backends(HardwareProfile(
        platform="linux",
        machine="x86_64",
        python="3.12",
        ram_gb=4,
        disk_free_gb=2,
    ))

    assert plan.ocr_backend == "paddleocr"
    assert plan.vsr_backend == "fallback"


def test_detect_hardware_reads_linux_gpu_probes(monkeypatch, tmp_path):
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        text = "AMD Radeon RX 6600" if command == ["lspci"] else ""
        if command == ["rocminfo"]:
            return SimpleNamespace(returncode=0, stdout="gfx1032", stderr="")
        if command == ["vulkaninfo", "--summary"]:
            return SimpleNamespace(returncode=0, stdout="Vulkan", stderr="")
        return SimpleNamespace(returncode=0, stdout=text, stderr="")

    monkeypatch.setattr(
        "autodub.hardware.platform.machine", lambda: "x86_64")
    profile = detect_hardware(
        runner=runner, disk_path=str(tmp_path), platform_name="linux")

    assert profile.amd is True
    assert profile.rocm is True
    assert profile.vulkan is True
    assert ["lspci"] in commands
