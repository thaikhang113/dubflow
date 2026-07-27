#!/usr/bin/env python3
"""Service-free contract tests for the single Bilibili processing action."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


HOST_SERVER = Path("/home/haonguyen/.local/bin/openclaw-host-runner-server.py")


def load_server_module():
    spec = importlib.util.spec_from_file_location("bilibili_host_runner_under_test", HOST_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BilibiliProcessContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.module = load_server_module()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalizes_ngoc_huyen_and_serializes_full_branding(self) -> None:
        validated = self.module.validate_bilibili_process_payload({
            "action": "bilibili-process",
            "url": "https://www.bilibili.com/video/BV1example",
            "voice": "Ngọc Huyền",
            "branding": {
                "enabled": True,
                "profile": "bilibili_top_left_block",
                "blur_uploader_block": True,
                "replace_logo": True,
                "include_intro": True,
                "include_outro": True,
            },
        })

        request = self.module.bilibili_process_queue_fields(validated)
        self.assertEqual(request["ACTION"], "bilibili-process")
        self.assertEqual(request["VOICE_PRESET"], "ai33:vbee_hn_female_ngochuyen_full_48k-fhg")
        self.assertEqual(request["BILIBILI_BRANDING"], "1")
        self.assertEqual(request["BILIBILI_BRAND_INCLUDE_INTRO"], "1")
        self.assertEqual(request["BILIBILI_BRAND_INCLUDE_OUTRO"], "1")

    def test_defaults_branding_off(self) -> None:
        validated = self.module.validate_bilibili_process_payload({
            "action": "bilibili-process",
            "url": "https://www.bilibili.com/video/BV1example",
            "voice": "Ngoc Huyen",
        })

        request = self.module.bilibili_process_queue_fields(validated)
        self.assertEqual(request["BILIBILI_BRANDING"], "0")
        self.assertEqual(request["BILIBILI_BRAND_INCLUDE_INTRO"], "0")
        self.assertEqual(request["BILIBILI_BRAND_INCLUDE_OUTRO"], "0")

    def test_tracking_url_is_canonicalized_before_queueing(self) -> None:
        validated = self.module.validate_bilibili_process_payload({
            "action": "bilibili-process",
            "url": "https://www.bilibili.com/video/BV1example?vd_source=tracking#reply",
            "voice": "Ngoc Huyen",
        })
        self.assertEqual(
            validated["url"],
            "https://www.bilibili.com/video/BV1example",
        )
        self.assertEqual(
            self.module.bilibili_process_queue_fields(validated)["URL"],
            "https://www.bilibili.com/video/BV1example",
        )

    def test_rejects_unknown_or_untrusted_fields(self) -> None:
        with self.assertRaises(ValueError):
            self.module.validate_bilibili_process_payload({
            "action": "bilibili-process",
            "url": "https://www.bilibili.com/video/BV1example",
            "voice": "Ngoc Huyen",
            "ninerouter_model": "not-user-controlled",
            })

    def test_rejects_child_branding_when_disabled(self) -> None:
        with self.assertRaises(ValueError):
            self.module.validate_bilibili_process_payload({
            "action": "bilibili-process",
            "url": "https://www.bilibili.com/video/BV1example",
            "voice": "Ngoc Huyen",
            "branding": {"enabled": False, "include_intro": True},
            })

    def test_direct_run_uses_validated_url_voice_and_branding_environment(self) -> None:
        url = "https://www.bilibili.com/video/BV1example"
        validated = self.module.validate_bilibili_process_payload({
            "action": "bilibili-process",
            "url": url,
            "voice": "Ngọc Huyền",
            "branding": {
                "enabled": True,
                "profile": "bilibili_top_left_block",
                "blur_uploader_block": True,
                "replace_logo": True,
                "include_intro": True,
                "include_outro": False,
            },
        })

        self.assertEqual(
            self.module.bilibili_process_direct_command(validated),
            ["run-bilibili", url, "ai33:vbee_hn_female_ngochuyen_full_48k-fhg"],
        )
        self.assertEqual(
            self.module.bilibili_process_runtime_fields(validated),
            {
                "BILIBILI_BRANDING": "1",
                "BILIBILI_BRAND_INCLUDE_INTRO": "1",
                "BILIBILI_BRAND_INCLUDE_OUTRO": "0",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
