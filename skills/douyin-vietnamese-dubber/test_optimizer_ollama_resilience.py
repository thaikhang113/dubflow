#!/usr/bin/env python3
"""Focused regressions for Ollama batch translation resilience."""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parent
OPTIMIZER = SKILL_DIR / "viet_dub_timing_optimizer.py"
STRUCTURED_JSON = SKILL_DIR / "structured_json.py"


def load_optimizer():
    skill_dir = str(SKILL_DIR)
    if skill_dir not in sys.path:
        sys.path.insert(0, skill_dir)
    spec = importlib.util.spec_from_file_location("optimizer_ollama_resilience", OPTIMIZER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_structured_json():
    spec = importlib.util.spec_from_file_location("structured_json_test", STRUCTURED_JSON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_inline_rewrite_chat(provider):
    """Extract the post-probe heredoc client so its request behavior is executable."""
    script = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
    client_source = script[script.index("def _rw_chat("):script.index("def rewrite_dub(")]
    namespace = {"json": json, "os": os, "time": __import__("time"), "urllib": __import__("urllib")}
    exec(client_source, namespace)
    namespace.update({
        "_rw_api_base": "http://ollama" if provider == "ollama" else "http://router",
        "_rw_api_key": "test-key",
        "_rw_model": "test-model",
        "_rw_api_provider": provider,
        "_rw_max_retries": 0,
        "_rw_chat_timeout": 1,
    })
    return namespace["_rw_chat"]


class OptimizerOllamaResilienceTests(unittest.TestCase):
    def setUp(self):
        self.optimizer = load_optimizer()

    def test_ollama_chat_requests_json_format(self):
        captured = {}

        class Response:
            def read(self):
                return json.dumps({"message": {"content": "{}"}}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return Response()

        with mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            self.optimizer.chat("http://ollama", "unused", "model", [{"role": "user", "content": "hi"}], api_provider="ollama")

        self.assertEqual("json", captured["payload"]["format"])

    def test_non_ollama_chat_does_not_request_ollama_json_format(self):
        captured = {}

        class Response:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return Response()

        with mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            self.optimizer.chat("http://router", "key", "model", [{"role": "user", "content": "hi"}])

        self.assertNotIn("format", captured["payload"])

    def test_ollama_empty_structured_response_retries_once_without_format(self):
        requests = []

        class Response:
            def __init__(self, content):
                self.content = content

            def read(self):
                return json.dumps({"message": {"content": self.content}}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response("   " if len(requests) == 1 else '{"items": []}')

        messages = [{"role": "user", "content": "hi"}]
        with mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(
                '{"items": []}',
                self.optimizer.chat("http://ollama", "unused", "model", messages, api_provider="ollama"),
            )

        self.assertEqual(2, len(requests))
        self.assertEqual("json", requests[0]["format"])
        self.assertNotIn("format", requests[1])
        self.assertEqual(requests[0]["messages"], requests[1]["messages"])
        self.assertEqual(requests[0]["options"], requests[1]["options"])
        self.assertEqual(requests[0]["stream"], requests[1]["stream"])

    def test_ollama_nonempty_malformed_response_does_not_compatibility_retry(self):
        requests = []

        class Response:
            def read(self):
                return b'{"message": {"content": "not valid json"}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response()

        with mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(
                "not valid json",
                self.optimizer.chat("http://ollama", "unused", "model", [{"role": "user", "content": "hi"}], api_provider="ollama"),
            )

        self.assertEqual(1, len(requests))
        self.assertEqual("json", requests[0]["format"])

    def test_ollama_second_empty_response_fails_after_two_requests(self):
        requests = []

        class Response:
            def read(self):
                return b'{"message": {"content": " "}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response()

        with mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaisesRegex(RuntimeError, "Ollama không trả nội dung"):
                self.optimizer.chat("http://ollama", "unused", "model", [{"role": "user", "content": "hi"}], api_provider="ollama")

        self.assertEqual(2, len(requests))
        self.assertEqual("json", requests[0]["format"])
        self.assertNotIn("format", requests[1])

    def test_non_ollama_uses_one_unformatted_request_without_retry(self):
        requests = []

        class Response:
            def read(self):
                return b'{"choices": [{"message": {"content": "ok"}}]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response()

        with mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual("ok", self.optimizer.chat("http://router", "key", "model", [{"role": "user", "content": "hi"}]))

        self.assertEqual(1, len(requests))
        self.assertNotIn("format", requests[0])

    def test_ollama_network_errors_use_only_existing_outer_retries(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            raise self.optimizer.urllib.error.URLError("offline")

        with mock.patch.object(self.optimizer, "env_int", return_value=1), \
             mock.patch.object(self.optimizer.time, "sleep"), \
             mock.patch.object(self.optimizer.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaisesRegex(RuntimeError, "network"):
                self.optimizer.chat("http://ollama", "unused", "model", [{"role": "user", "content": "hi"}], api_provider="ollama")

        self.assertEqual(2, len(requests))
        self.assertTrue(all(request["format"] == "json" for request in requests))

    def test_ollama_default_batch_is_conservative_but_override_is_preserved(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPTIMIZER_TRANSLATE_BATCH_SIZE", None)
            self.assertEqual(10, self.optimizer.translate_batch_size_for_provider("ollama"))
            self.assertEqual(20, self.optimizer.translate_batch_size_for_provider("ninerouter"))
        with mock.patch.dict(os.environ, {"OPTIMIZER_TRANSLATE_BATCH_SIZE": "17"}, clear=False):
            self.assertEqual(17, self.optimizer.translate_batch_size_for_provider("ollama"))

    def test_extract_json_accepts_complete_object_with_prose_and_extra_braces(self):
        text = 'Model note {not-json}; result follows:\n```json\n{"items": [{"group_id": 1}]}\n```\nthanks }'
        self.assertEqual({"items": [{"group_id": 1}]}, self.optimizer.extract_json(text))

    def test_extract_json_rejects_malformed_and_truncated_objects(self):
        with self.assertRaises(json.JSONDecodeError):
            self.optimizer.extract_json('prefix {"items": [{"group_id": 1}]')
        with self.assertRaises(json.JSONDecodeError):
            self.optimizer.extract_json('prefix {"items": [}')

    def test_shared_parser_accepts_first_complete_object_amid_prose_and_braces(self):
        parser = load_structured_json()
        content = 'note {not-json}; ```json\n{"items": [{"group_id": 1}]}\n``` trailing }'
        self.assertEqual({"items": [{"group_id": 1}]}, parser.extract_first_json_object(content))

    def test_shared_parser_rejects_empty_malformed_and_truncated_input(self):
        parser = load_structured_json()
        for content in ("", "no JSON here", '{"items": [}', '{"items": [{"id": 1}]'):
            with self.subTest(content=content):
                with self.assertRaises(json.JSONDecodeError):
                    parser.extract_first_json_object(content)

    def test_optimizer_extract_json_delegates_to_shared_parser(self):
        with mock.patch.object(self.optimizer, "extract_first_json_object", return_value={"ok": True}) as parse:
            self.assertEqual({"ok": True}, self.optimizer.extract_json("ignored"))
        parse.assert_called_once_with("ignored")

    def test_inline_rewrite_ollama_payload_declares_json_format(self):
        script = (SKILL_DIR / "run.sh").read_text(encoding="utf-8")
        inline_chat = script[script.index("def _rw_chat("):script.index("def rewrite_dub(")]
        self.assertIn("'format': 'json'", inline_chat)
        self.assertIn("def _rw_json_object(content):", script)
        self.assertIn("return extract_first_json_object(content)", script)

    def test_inline_rewrite_retries_once_without_format_after_empty_structured_ollama_response(self):
        requests = []

        class Response:
            def __init__(self, content):
                self.content = content

            def read(self):
                return json.dumps({"message": {"content": self.content}}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response("   " if len(requests) == 1 else '{"ok": true}')

        chat = load_inline_rewrite_chat("ollama")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual('{"ok": true}', chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(2, len(requests))
        self.assertEqual("json", requests[0]["format"])
        self.assertNotIn("format", requests[1])
        self.assertEqual(requests[0]["messages"], requests[1]["messages"])

    def test_inline_rewrite_does_not_fallback_when_structured_ollama_response_is_nonempty(self):
        requests = []

        class Response:
            def read(self):
                return b'{"message":{"content":"not valid json"}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response()

        chat = load_inline_rewrite_chat("ollama")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual("not valid json", chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(1, len(requests))
        self.assertEqual("json", requests[0]["format"])

    def test_inline_rewrite_non_ollama_uses_one_unformatted_request(self):
        requests = []

        class Response:
            def read(self):
                return b'{"choices":[{"message":{"content":"not valid json"}}]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response()

        chat = load_inline_rewrite_chat("ninerouter")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual("not valid json", chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(1, len(requests))
        self.assertNotIn("format", requests[0])

    def test_adaptive_recovery_splits_ten_to_five_then_succeeds(self):
        payloads = [{"group_id": index} for index in range(10)]
        attempted_sizes = []

        def fake_batch(group_payloads, *args, **kwargs):
            attempted_sizes.append(len(group_payloads))
            if len(group_payloads) > 5:
                self.optimizer.extract_json('{"items": [}')
            return {item["group_id"]: ([], "ok") for item in group_payloads}

        with mock.patch.object(self.optimizer, "translate_groups_batch", fake_batch):
            result = self.optimizer.translate_groups_adaptive(payloads, "base", "key", "model")

        self.assertEqual(set(range(10)), set(result))
        self.assertEqual([10, 5, 5], attempted_sizes)


if __name__ == "__main__":
    unittest.main()
