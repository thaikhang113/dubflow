"""Stable terminal-state mapping for voice-sync gate outcomes."""
import json

def normalize_resona_grouped_source_cue_ids(stats):
    """Read optional Resona grouping metadata from serialized TTS stats."""
    groups = stats.get("resona_short_grouped_source_cue_ids") if isinstance(stats, dict) else None
    if not isinstance(groups, list):
        return []
    return [group for group in groups if isinstance(group, list)]

def build_voice_sync_fallback_report(error_text="", stats_available=False):
    """Return safe report when checker fails before serializing its report."""
    return {
        "status": "fail",
        "error_code": "VoiceSyncReportBuildFailed",
        "error_message": "Voice-sync checker failed before writing its quality report.",
        "stats_available": bool(stats_available),
        "block_organization": True,
    }

def gate_terminal_status(exit_status):
    """Map unexpected gate failures to a safe, non-organizing terminal status."""
    if int(exit_status) not in (0, 7, 8):
        return {
            "status": "needs_attention",
            "error_code": "VoiceSyncGateInternalError",
            "block_organization": True,
        }
    return None

def final_report_status(report_text):
    """Fail closed when the mandatory final voice-sync report is absent or invalid."""
    if report_text is None:
        return {
            "status": "needs_attention",
            "error_code": "VoiceSyncReportMissing",
            "message": "Thiếu voice_sync_quality_report.json sau TTS/render; không organize output.",
            "block_organization": True,
        }
    try:
        report = json.loads(report_text)
        status = report.get("status") if isinstance(report, dict) else None
    except (TypeError, ValueError):
        status = None
    if status in ("ok", "warning"):
        return None
    if status == "fail":
        return {
            "status": "needs_attention",
            "error_code": "VoiceSyncReportFailed",
            "message": "voice_sync_quality_report.json báo fail; không organize output.",
            "block_organization": True,
        }
    return {
        "status": "needs_attention",
        "error_code": "VoiceSyncReportUnreadable",
        "message": "voice_sync_quality_report.json không đọc được hoặc thiếu status hợp lệ; không organize output.",
        "block_organization": True,
    }
