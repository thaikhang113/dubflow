import sys
import threading
import time
from autodub.cancel import (
    cancel_processes,
    cancel_scope,
    clear_cancel_request,
    is_cancel_requested,
    run_registered,
)
from autodub.progress import PipelineCancelled


def test_scoped_cancellation_isolates_workers() -> None:
    clear_cancel_request()
    gui_result: list[BaseException | str] = []
    remote_result: list[BaseException | str] = []

    gui_started = threading.Event()
    remote_started = threading.Event()

    def run_gui() -> None:
        with cancel_scope("gui"):
            gui_started.set()
            try:
                run_registered(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    timeout=20,
                )
                gui_result.append("finished")
            except BaseException as exc:
                gui_result.append(exc)

    def run_remote() -> None:
        with cancel_scope("remote"):
            remote_started.set()
            try:
                run_registered(
                    [sys.executable, "-c", "import time; time.sleep(1)"],
                    timeout=10,
                )
                remote_result.append("finished")
            except BaseException as exc:
                remote_result.append(exc)

    t_gui = threading.Thread(target=run_gui)
    t_remote = threading.Thread(target=run_remote)

    t_gui.start()
    t_remote.start()

    assert gui_started.wait(timeout=5)
    assert remote_started.wait(timeout=5)
    time.sleep(0.2)

    # Cancel ONLY gui scope
    cancel_processes(scope="gui")

    t_gui.join(timeout=5)
    assert not t_gui.is_alive()
    assert gui_result and isinstance(gui_result[0], PipelineCancelled)

    # Remote should still be running and finish successfully
    t_remote.join(timeout=5)
    assert not t_remote.is_alive()
    assert remote_result == ["finished"]

    clear_cancel_request()
    assert not is_cancel_requested("gui")
    assert not is_cancel_requested("remote")
