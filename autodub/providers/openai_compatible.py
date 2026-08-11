"""OpenAI-compatible translation provider.

Works with Ollama, llama.cpp servers, OpenRouter, and other endpoints that
implement ``/models`` and ``/chat/completions``.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from autodub.text.translate_common import TranslateError, parse_response_segments


class OpenAICompatibleError(RuntimeError):
    """Provider failure with secrets removed from its public message."""


def normalize_endpoint(endpoint: str) -> str:
    value = str(endpoint or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def _redact(text: object, secret: str) -> str:
    return str(text).replace(secret, "[REDACTED]") if secret else str(text)


def build_translation_prompt(
    segments: list[dict],
    context: dict[str, str] | None = None,
    previous: list[dict] | None = None,
) -> str:
    context = context or {}
    previous = previous or []
    payload = [
        {
            "id": int(item["id"]),
            "text": str(item.get("text", "")),
            **({"duration": round(float(item["duration"]), 3)}
               if item.get("duration") else {}),
            **({"max_chars": int(item["max_chars"])}
               if item.get("max_chars") else {}),
        }
        for item in segments
    ]
    return (
        "Bạn là biên dịch viên Trung-Việt cho video lồng tiếng. "
        "Dịch tự nhiên để nghe, giữ đúng ý, nhân vật, xưng hô và sắc thái. "
        "Không giải thích, không thêm câu. Trả đúng JSON dạng "
        '{"segments":[{"id":number,"text_vi":"..."}]}. '
        "Giữ id, không bỏ câu, không để trống text_vi.\n\n"
        f"Ngữ cảnh: {json.dumps(context, ensure_ascii=False)}\n"
        f"Câu trước để giữ mạch: {json.dumps(previous, ensure_ascii=False)}\n"
        f"Các câu cần dịch: {json.dumps(payload, ensure_ascii=False)}"
    )


class OpenAICompatibleProvider:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "",
        session: Any | None = None,
        timeout: float = 120.0,
    ):
        self.endpoint = normalize_endpoint(endpoint)
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def list_models(self) -> list[str]:
        if not self.endpoint:
            raise OpenAICompatibleError("Thiếu endpoint dịch.")
        try:
            response = self.session.get(
                f"{self.endpoint}/models", headers=self._headers(), timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise OpenAICompatibleError(
                _redact(f"Không tải được danh sách model: {exc}", self.api_key)
            ) from exc
        items = data.get("data", []) if isinstance(data, dict) else []
        models = [
            str(item.get("id", "")).strip()
            for item in items
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        ]
        if not models:
            raise OpenAICompatibleError("Endpoint không trả về model hợp lệ.")
        return models

    def check_model(self) -> None:
        """Send a minimal request to prove selected model can answer."""
        if not self.endpoint or not self.model:
            raise OpenAICompatibleError("Thiếu endpoint hoặc model dịch.")
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "Trả lời OK."}],
        }
        try:
            response = self.session.post(
                f"{self.endpoint}/chat/completions",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("choices"):
                raise ValueError("Phản hồi không có choices.")
        except Exception as exc:
            raise OpenAICompatibleError(
                _redact(f"Model không trả lời: {exc}", self.api_key)
            ) from exc

    def translate(
        self,
        segments: list[dict],
        context: dict[str, str] | None = None,
        previous: list[dict] | None = None,
    ) -> list[dict]:
        if not self.endpoint or not self.model:
            raise OpenAICompatibleError("Thiếu endpoint hoặc model dịch.")
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "Chỉ trả JSON hợp lệ. Không dùng markdown fence.",
                },
                {
                    "role": "user",
                    "content": build_translation_prompt(segments, context, previous),
                },
            ],
        }
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.post(
                    f"{self.endpoint}/chat/completions",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                return parse_response_segments(str(content))
            except Exception as exc:
                last = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise OpenAICompatibleError(
            _redact(f"Dịch thất bại sau 3 lần thử: {last}", self.api_key)
        ) from last
