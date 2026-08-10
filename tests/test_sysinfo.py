"""Test autodub.sysinfo — đọc RAM không phụ thuộc thư viện ngoài."""
from autodub import sysinfo


def test_ram_readings_positive_or_none():
    total = sysinfo.total_ram_gb()
    avail = sysinfo.available_ram_gb()
    assert total is None or total > 0
    assert avail is None or avail > 0
    if total is not None and avail is not None:
        assert avail <= total


def test_failure_returns_none(monkeypatch):
    monkeypatch.setattr(sysinfo, "_memory_status", lambda: None)
    sysinfo.total_ram_gb.cache_clear()
    assert sysinfo.total_ram_gb() is None
    assert sysinfo.available_ram_gb() is None
    sysinfo.total_ram_gb.cache_clear()


def test_posix_fallback_math(monkeypatch):
    monkeypatch.setattr(sysinfo, "_memory_status",
                        lambda: (8 * 1024 ** 3, 4 * 1024 ** 3))
    sysinfo.total_ram_gb.cache_clear()
    assert sysinfo.total_ram_gb() == 8.0
    assert sysinfo.available_ram_gb() == 4.0
    sysinfo.total_ram_gb.cache_clear()
