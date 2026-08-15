import os


def test_configure_numeric_threads_limits_blas_and_onnx(monkeypatch):
    from autodub.speech.tts.vieneu_worker import _configure_numeric_threads

    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "ORT_INTRA_OP_NUM_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)

    _configure_numeric_threads(2)

    assert os.environ["OMP_NUM_THREADS"] == "2"
    assert os.environ["OPENBLAS_NUM_THREADS"] == "2"
    assert os.environ["MKL_NUM_THREADS"] == "2"
    assert os.environ["NUMEXPR_NUM_THREADS"] == "2"
    assert os.environ["ORT_INTRA_OP_NUM_THREADS"] == "2"
