#!/usr/bin/env python3
"""Contract tests for the fixed Trend Scout host-runner actions.

The host runner itself deliberately lives outside the OpenClaw workspace.  This
test loads that boundary with a harmless fake runner so the scheduling contract
can be verified without Docker, Bilibili, or any secret.
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path


HOST_SERVER = Path("/home/haonguyen/.local/bin/openclaw-host-runner-server.py")


def load_server_module():
    spec = importlib.util.spec_from_file_location("host_runner_under_test", HOST_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixedTrendActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.args_path = root / "runner-args.txt"
        self.token_path = root / "token"
        self.token_path.write_text("contract-token", encoding="utf-8")
        self.runner_path = root / "fake-runner.sh"
        self.runner_path.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$@\" > \"$ARGS_PATH\"\n"
            "printf '{\\\"ok\\\":true}\\n'\n",
            encoding="utf-8",
        )
        self.runner_path.chmod(0o755)

        self.module = load_server_module()
        self.module.RUNNER = str(self.runner_path)
        self.module.TOKEN_FILE = str(self.token_path)
        self.module.ASYNC_LOG_DIR = str(root / "logs")
        self.module.QUEUE_DIR = str(root / "queue")
        os.environ["ARGS_PATH"] = str(self.args_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.module.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.tmp.cleanup()
        os.environ.pop("ARGS_PATH", None)

    def post(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        body = json.dumps(payload).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request(
            "POST",
            "/run",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "X-OpenClaw-Host-Runner-Token": "contract-token",
            },
        )
        response = conn.getresponse()
        payload_out = json.loads(response.read().decode("utf-8"))
        conn.close()
        return response.status, payload_out

    def runner_args(self) -> list[str]:
        return self.args_path.read_text(encoding="utf-8").splitlines()

    def test_collection_tick_has_no_user_supplied_arguments(self) -> None:
        status, response = self.post({"action": "trend-collection-tick"})

        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertEqual(self.runner_args(), ["trend-collection-tick"])

    def test_report_prepare_only_accepts_allowlisted_kind_and_dedupe(self) -> None:
        status, response = self.post(
            {
                "action": "trend-report-prepare",
                "report_kind": "digest",
                "dedupe_key": "digest-20260714-16",
            }
        )

        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertEqual(
            self.runner_args(),
            ["trend-report-prepare", "digest", "digest-20260714-16"],
        )

    def test_report_actions_reject_a_smuggled_url(self) -> None:
        status, response = self.post(
            {
                "action": "trend-report-prepare",
                "url": "$(do-not-run)",
                "report_kind": "digest",
                "dedupe_key": "digest-20260714-16",
            }
        )

        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "invalid_report_arguments")


if __name__ == "__main__":
    unittest.main(verbosity=2)
