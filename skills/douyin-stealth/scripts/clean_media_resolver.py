"""Policy-only selection and lightweight validation for Douyin media candidates.

The resolver deliberately keeps signed CDN URLs in process memory only.  Its
public report contains a one-way candidate id and metadata suitable for status
updates, never a direct media URL or query string.
"""

from __future__ import annotations

import hashlib
import ipaddress
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional


CLEAN_ONLY = "clean_only"
ALLOW_WATERMARKED_FALLBACK = "allow_watermarked_fallback"
SUPPORTED_POLICIES = {CLEAN_ONLY, ALLOW_WATERMARKED_FALLBACK}

_MEDIA_HOST_SUFFIXES = (
    "douyinvod.com",
    "bytecdn.cn",
    "byteimg.com",
    "snssdk.com",
    "pstatp.com",
    "zjcdn.com",
    "bytevolc.com",
)
_WATERMARK_MARKERS = ("playwm", "watermark", "water_mark", "with_logo")
_CLEAN_HINT_MARKERS = ("nwm", "no_watermark", "nowatermark", "without_watermark", "clean")
_VIDEO_URL_MARKERS = (".mp4", "/play", "play_addr", "/video/tos/", "video_mp4")
_MAX_DECLARED_MEDIA_BYTES = 512 * 1024 * 1024
_PUBLIC_REJECTION_CATEGORIES = ("unsafe_url", "not_video", "watermarked", "unknown")
_PUBLIC_SOURCE_CATEGORIES = (
    "network_response",
    "network_request",
    "player_state",
    "dom",
    "script_state",
    "other",
)


def _header(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value or "")
    return ""


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def safe_rejection_summary(rejected_counts: Mapping[str, Any]) -> str:
    """Expose only a fixed, non-sensitive set of rejection counters."""
    parts = []
    for category in _PUBLIC_REJECTION_CATEGORIES:
        count = _int_or_zero(rejected_counts.get(category))
        if count:
            parts.append(f"{category}={count}")
    return ",".join(parts) if parts else "none"


def safe_candidate_source_summary(candidates: Iterable[Mapping[str, Any]]) -> str:
    """Count only fixed source families, never a raw source detail or URL."""
    counts = {category: 0 for category in _PUBLIC_SOURCE_CATEGORIES}
    for raw in candidates:
        source = str(raw.get("source") or "")
        if source.startswith("network_response:"):
            category = "network_response"
        elif source.startswith("network_request:"):
            category = "network_request"
        elif source.startswith("player_state:"):
            category = "player_state"
        elif source.startswith("dom_") or source == "dom_source":
            category = "dom"
        elif source == "script_state":
            category = "script_state"
        else:
            category = "other"
        counts[category] += 1
    return ",".join(f"{category}={counts[category]}" for category in _PUBLIC_SOURCE_CATEGORIES if counts[category]) or "none"


def is_safe_douyin_media_url(url: str) -> bool:
    """Allow only HTTPS media hosts expected from Douyin/ByteDance CDN traffic."""
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443):
            return False
        host = parsed.hostname.lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        return any(host == suffix or host.endswith("." + suffix) for suffix in _MEDIA_HOST_SUFFIXES)
    except (TypeError, ValueError):
        return False


def is_videoish_candidate(url: str, content_type: str = "") -> bool:
    haystack = str(url or "").lower()
    ctype = str(content_type or "").lower()
    return ctype.startswith("video/") or any(marker in haystack for marker in _VIDEO_URL_MARKERS)


def _cleanliness_for(url: str, source: str, content_type: str) -> tuple[str, tuple[str, ...]]:
    haystack = str(url or "").lower()
    source = str(source or "")
    ctype = str(content_type or "").lower()
    if any(marker in haystack for marker in _WATERMARK_MARKERS):
        return "watermarked", ("watermark_url_marker",)

    evidence = []
    if source.startswith("player_state:") and ctype.startswith("video/"):
        evidence.append("player_state_video_field")
        if any(marker in haystack for marker in _CLEAN_HINT_MARKERS):
            evidence.append("url_clean_hint_supplemental")
            return "verified_clean", tuple(evidence)

    if source.startswith("network_response:") and (
        ctype.startswith("video/") or source == "network_response:media"
    ):
        evidence.append("network_media_response")
        if any(marker in haystack for marker in _CLEAN_HINT_MARKERS):
            evidence.append("url_clean_hint_supplemental")
        return "likely_clean", tuple(evidence)

    if source.startswith("network_request:"):
        # The request collector only emits this source after its URL-level video
        # predicate succeeds. Playwright may label the same video request as
        # media, fetch, or unknown; this is provisional—not verified—and the
        # caller must still pass the bounded Range/MP4 gate before downloading.
        evidence_name = (
            "network_media_request_provisional"
            if source == "network_request:media"
            else "network_video_request_provisional"
        )
        return "likely_clean", (evidence_name,)

    return "unknown", tuple(evidence)


@dataclass(frozen=True)
class MediaCandidate:
    url: str = field(repr=False)
    source: str
    content_type: str = ""
    content_length: int = 0
    cleanliness: str = "unknown"
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "MediaCandidate":
        url = str(raw.get("url") or "")
        source = str(raw.get("source") or "unknown")
        content_type = str(raw.get("content_type") or "")
        cleanliness, evidence = _cleanliness_for(url, source, content_type)
        return cls(
            url=url,
            source=source,
            content_type=content_type,
            content_length=_int_or_zero(raw.get("content_length")),
            cleanliness=cleanliness,
            evidence=evidence,
        )

    @property
    def candidate_id(self) -> str:
        return hashlib.sha256(self.url.encode("utf-8", "ignore")).hexdigest()[:16]

    @property
    def score(self) -> int:
        base = {
            "verified_clean": 400,
            "likely_clean": 250,
            "unknown": 50,
            "watermarked": -500,
        }.get(self.cleanliness, -1000)
        if self.source.startswith("network_response:"):
            base += 60
        if self.source.startswith("player_state:"):
            base += 80
        if self.content_type.lower().startswith("video/"):
            base += 30
        if self.content_length:
            base += min(40, self.content_length // (1024 * 1024))
        return base

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "content_type": self.content_type.split(";", 1)[0].lower(),
            "content_length": self.content_length,
            "cleanliness": self.cleanliness,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class MediaResolution:
    policy: str
    status: str
    selected: Optional[MediaCandidate] = field(default=None, repr=False)
    ordered_candidates: tuple[MediaCandidate, ...] = field(default=(), repr=False)
    rejected_counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.selected is not None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy": self.policy,
            "selected": self.selected.public_dict() if self.selected else None,
            "accepted_candidate_count": len(self.ordered_candidates),
            "rejected_counts": dict(self.rejected_counts),
        }


@dataclass(frozen=True)
class ProbeValidation:
    accepted: bool
    reason: str
    declared_total_bytes: int = 0


def _looks_like_html(body: bytes) -> bool:
    prefix = body[:512].lstrip().lower()
    return prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html")


def _looks_like_iso_bmff(body: bytes) -> bool:
    return len(body) >= 8 and body[4:8] in (b"ftyp", b"styp")


def validate_media_probe_response(status_code: int, headers: Mapping[str, Any], body: bytes) -> ProbeValidation:
    """Validate a bounded range response before a full browser-context fetch."""
    if status_code not in (200, 206):
        return ProbeValidation(False, "unexpected_status")
    if status_code == 206 and not _header(headers, "content-range"):
        return ProbeValidation(False, "missing_content_range")
    if not body or _looks_like_html(body):
        return ProbeValidation(False, "not_video_payload")

    ctype = _header(headers, "content-type").lower()
    if not ctype.startswith("video/") and not _looks_like_iso_bmff(body):
        return ProbeValidation(False, "not_video_payload")

    total = 0
    content_range = _header(headers, "content-range")
    if "/" in content_range:
        total = _int_or_zero(content_range.rsplit("/", 1)[1])
    if not total:
        total = _int_or_zero(_header(headers, "content-length"))
    if total > _MAX_DECLARED_MEDIA_BYTES:
        return ProbeValidation(False, "declared_size_too_large", total)
    return ProbeValidation(True, "ok", total)


def resolve_media_candidates(
    candidates: Iterable[Mapping[str, Any]], *, policy: str = CLEAN_ONLY
) -> MediaResolution:
    """Rank candidates without allowing a watermarked fallback under clean_only."""
    if policy not in SUPPORTED_POLICIES:
        raise ValueError(f"unsupported media policy: {policy}")

    rejected = {"unsafe_url": 0, "not_video": 0, "watermarked": 0, "unknown": 0}
    accepted = []
    for raw in candidates:
        candidate = MediaCandidate.from_mapping(raw)
        if not is_safe_douyin_media_url(candidate.url):
            rejected["unsafe_url"] += 1
            continue
        if not is_videoish_candidate(candidate.url, candidate.content_type):
            rejected["not_video"] += 1
            continue
        if policy == CLEAN_ONLY and candidate.cleanliness == "watermarked":
            rejected["watermarked"] += 1
            continue
        if policy == CLEAN_ONLY and candidate.cleanliness == "unknown":
            rejected["unknown"] += 1
            continue
        accepted.append(candidate)

    ordered = tuple(sorted(accepted, key=lambda item: (item.score, item.content_length), reverse=True))
    return MediaResolution(
        policy=policy,
        status="resolved" if ordered else "no_acceptable_candidate",
        selected=ordered[0] if ordered else None,
        ordered_candidates=ordered,
        rejected_counts={key: value for key, value in rejected.items() if value},
    )
