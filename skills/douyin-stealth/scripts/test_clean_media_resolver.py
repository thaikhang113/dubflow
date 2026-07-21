import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clean_media_resolver import (
    CLEAN_ONLY,
    ALLOW_WATERMARKED_FALLBACK,
    resolve_media_candidates,
    safe_candidate_source_summary,
    safe_rejection_summary,
    validate_media_probe_response,
)


def candidate(url, *, source="network_response:media", content_type="video/mp4", content_length=8_000_000):
    return {
        "url": url,
        "source": source,
        "content_type": content_type,
        "content_length": content_length,
    }


class CleanMediaResolverTests(unittest.TestCase):
    def test_fetch_defaults_prefer_clean_but_allow_watermarked_fallback(self):
        """The pipeline's default must continue when a clean stream is unavailable."""
        scripts_dir = str(Path(__file__).resolve().parent)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.path.insert(0, sys.argv[1]); "
                    "import fetch_douyin_v2; "
                    "print(fetch_douyin_v2.clean_media_policy())"
                ),
                scripts_dir,
            ],
            env={"PATH": os.defpath},
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(ALLOW_WATERMARKED_FALLBACK, result.stdout.strip())

    def test_clean_only_prefers_network_validated_candidate_and_rejects_playwm(self):
        result = resolve_media_candidates(
            [
                candidate("https://v3-dy-o.zjcdn.com/aweme/v1/playwm/?fixture=watermarked"),
                candidate("https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=clean"),
            ],
            policy=CLEAN_ONLY,
        )

        self.assertTrue(result.accepted)
        self.assertEqual("likely_clean", result.selected.cleanliness)
        self.assertNotIn("playwm", result.selected.url)
        self.assertEqual(1, result.rejected_counts["watermarked"])

    def test_clean_only_refuses_watermarked_fallback(self):
        result = resolve_media_candidates(
            [candidate("https://v3-dy-o.zjcdn.com/aweme/v1/playwm/?fixture=watermarked")],
            policy=CLEAN_ONLY,
        )

        self.assertFalse(result.accepted)
        self.assertEqual("no_acceptable_candidate", result.status)
        self.assertEqual(1, result.rejected_counts["watermarked"])

    def test_watermarked_fallback_requires_explicit_policy(self):
        result = resolve_media_candidates(
            [candidate("https://v3-dy-o.zjcdn.com/aweme/v1/playwm/?fixture=watermarked")],
            policy=ALLOW_WATERMARKED_FALLBACK,
        )

        self.assertTrue(result.accepted)
        self.assertEqual("watermarked", result.selected.cleanliness)

    def test_public_report_never_contains_candidate_url_or_query(self):
        direct_url = "https://v3-dy-o.zjcdn.com/aweme/v1/play/?opaque=fixture-value"
        result = resolve_media_candidates([candidate(direct_url)], policy=CLEAN_ONLY)
        report = result.to_public_dict()
        encoded = json.dumps(report, sort_keys=True)

        self.assertNotIn(direct_url, encoded)
        self.assertNotIn("fixture-value", encoded)
        self.assertEqual("likely_clean", report["selected"]["cleanliness"])
        self.assertIn("candidate_id", report["selected"])

    def test_network_media_response_without_mime_is_still_range_validated_likely_clean(self):
        result = resolve_media_candidates(
            [
                candidate(
                    "https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=media",
                    source="network_response:media",
                    content_type="",
                )
            ],
            policy=CLEAN_ONLY,
        )

        self.assertTrue(result.accepted)
        self.assertEqual("likely_clean", result.selected.cleanliness)

    def test_network_media_request_is_eligible_for_range_validation(self):
        result = resolve_media_candidates(
            [
                candidate(
                    "https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=request-media",
                    source="network_request:media",
                    content_type="",
                )
            ],
            policy=CLEAN_ONLY,
        )

        self.assertTrue(result.accepted)
        self.assertEqual("likely_clean", result.selected.cleanliness)
        self.assertIn("network_media_request_provisional", result.selected.evidence)

    def test_network_video_request_with_unknown_resource_type_is_provisional(self):
        result = resolve_media_candidates(
            [
                candidate(
                    "https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=request-unknown",
                    source="network_request:unknown",
                    content_type="",
                )
            ],
            policy=CLEAN_ONLY,
        )

        self.assertTrue(result.accepted)
        self.assertEqual("likely_clean", result.selected.cleanliness)
        self.assertIn("network_video_request_provisional", result.selected.evidence)

    def test_network_video_request_with_non_media_resource_type_is_provisional(self):
        result = resolve_media_candidates(
            [
                candidate(
                    "https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=request-fetch",
                    source="network_request:fetch",
                    content_type="",
                )
            ],
            policy=CLEAN_ONLY,
        )

        self.assertTrue(result.accepted)
        self.assertEqual("likely_clean", result.selected.cleanliness)
        self.assertIn("network_video_request_provisional", result.selected.evidence)

    def test_rejects_non_cdn_and_unknown_cleanliness_when_clean_only(self):
        result = resolve_media_candidates(
            [
                candidate("https://example.invalid/movie.mp4"),
                candidate(
                    "https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=dom",
                    source="dom_video_currentSrc",
                    content_type="",
                ),
            ],
            policy=CLEAN_ONLY,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(1, result.rejected_counts["unsafe_url"])
        self.assertEqual(1, result.rejected_counts["unknown"])

    def test_rejection_summary_exposes_only_known_count_categories(self):
        summary = safe_rejection_summary(
            {"unsafe_url": 2, "unknown": 1, "untrusted_detail": "do-not-print"}
        )

        self.assertEqual("unsafe_url=2,unknown=1", summary)
        self.assertNotIn("untrusted_detail", summary)
        self.assertNotIn("do-not-print", summary)

    def test_candidate_source_summary_exposes_only_fixed_source_groups(self):
        summary = safe_candidate_source_summary(
            [
                candidate("https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=request", source="network_request:media"),
                candidate("https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=dom", source="dom_video_currentSrc"),
                candidate("https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=other", source="untrusted:do-not-print"),
            ]
        )

        self.assertEqual("network_request=1,dom=1,other=1", summary)
        self.assertNotIn("untrusted", summary)
        self.assertNotIn("do-not-print", summary)


class MediaProbeValidationTests(unittest.TestCase):
    def test_clean_selection_is_not_downloadable_until_range_probe_accepts_it(self):
        resolution = resolve_media_candidates(
            [candidate("https://v3-dy-o.zjcdn.com/aweme/v1/play/?fixture=selection")],
            policy=CLEAN_ONLY,
        )
        self.assertTrue(resolution.accepted)

        rejected_probe = validate_media_probe_response(
            206,
            {"content-type": "text/html", "content-range": "bytes 0-64/128"},
            b"<html>challenge</html>",
        )
        self.assertFalse(rejected_probe.accepted)

        accepted_probe = validate_media_probe_response(
            206,
            {"content-type": "video/mp4", "content-range": "bytes 0-64/8000000"},
            b"\x00\x00\x00\x18ftypisom" + b"x" * 64,
        )
        self.assertTrue(accepted_probe.accepted)

    def test_accepts_valid_range_probe(self):
        result = validate_media_probe_response(
            206,
            {
                "content-type": "video/mp4",
                "content-range": "bytes 0-65535/8000000",
                "content-length": "65536",
            },
            b"\x00\x00\x00\x18ftypisom" + b"x" * 64,
        )

        self.assertTrue(result.accepted)

    def test_rejects_html_redirect_body_even_if_status_is_successful(self):
        result = validate_media_probe_response(
            200,
            {"content-type": "text/html", "content-length": "128"},
            b"<!doctype html><html>verification required</html>",
        )

        self.assertFalse(result.accepted)
        self.assertEqual("not_video_payload", result.reason)

    def test_rejects_range_response_without_video_evidence(self):
        result = validate_media_probe_response(
            206,
            {"content-type": "application/octet-stream", "content-range": "bytes 0-3/4"},
            b"nope",
        )

        self.assertFalse(result.accepted)
        self.assertEqual("not_video_payload", result.reason)


if __name__ == "__main__":
    unittest.main()
