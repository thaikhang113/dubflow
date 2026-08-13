from pathlib import Path


def test_export_state_carries_quality_report_context() -> None:
    source = Path("autodub/pipeline.py").read_text(encoding="utf-8")

    assert '"clone_report": clone_report' in source
    assert '"worker_plan": worker_plan' in source
    assert 'state.get("clone_report") or {}' in source
    assert 'state.get("worker_plan") or {}' in source
