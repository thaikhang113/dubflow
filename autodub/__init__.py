"""autodub — automatic video dubbing into Vietnamese.

Public API used by the GUI:

    from autodub import Settings, DubPipeline, DubRequest, DubResult

    settings = Settings.load()
    pipeline = DubPipeline(settings, progress=my_callback, cancel_event=my_event)
    result = pipeline.run(DubRequest(url="https://...", voice="male"))
"""
from autodub.config import ConfigError, Settings
from autodub.languages import TARGETS, TargetLang, get_target
from autodub.pipeline import DubPipeline, DubRequest, DubResult
from autodub.progress import PipelineCancelled, ProgressEvent, ProgressFn

__all__ = [
    "ConfigError",
    "Settings",
    "TARGETS",
    "TargetLang",
    "get_target",
    "DubPipeline",
    "DubRequest",
    "DubResult",
    "PipelineCancelled",
    "ProgressEvent",
    "ProgressFn",
]

__version__ = "1.0.0"
