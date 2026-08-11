from autodub.media import downloader


def test_extract_info_retries_bilibili_412(monkeypatch):
    calls = []

    class Ydl:
        def extract_info(self, url, download):
            calls.append((url, download))
            if len(calls) == 1:
                raise RuntimeError("Unable to download JSON metadata: HTTP Error 412")
            return {"id": "BV-test"}

    sleeps = []
    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)

    result = downloader._extract_info_with_retry(Ydl(), "https://bilibili.test", attempts=2)

    assert result["id"] == "BV-test"
    assert len(calls) == 2
    assert sleeps == [2]
