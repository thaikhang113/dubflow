import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import google_flow_thumbnail


class GoogleFlowThumbnailTest(unittest.TestCase):
    def test_main_records_fatal_failure_in_bridge_status(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with (
                patch.object(sys, "argv", ["google_flow_thumbnail.py", str(output)]),
                patch.object(
                    google_flow_thumbnail,
                    "run",
                    new=AsyncMock(
                        side_effect=RuntimeError("CDP unavailable"),
                    ),
                ),
            ):
                self.assertEqual(google_flow_thumbnail.main(), 1)

            status = json.loads(
                (output / "thumbnail_flow_bridge_status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["phase"], "fatal")
            self.assertEqual(status["status"], "needs_user_attention")
            self.assertEqual(status["progress_percent"], 100)
            self.assertIn("CDP unavailable", status["detail"])


if __name__ == "__main__":
    unittest.main()
