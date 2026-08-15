from autodub.pipeline import _plan_tts_voice_groups


def test_tts_route_keeps_parallelism_for_single_voice():
    route = _plan_tts_voice_groups(
        "Main",
        [{"voice": ""}, {"voice": ""}, {"voice": ""}],
        lambda value: value or "Main",
        max_workers=3,
    )

    assert route.mode == "parallel"
    assert route.groups == [("Main", [0, 1, 2])]
    assert route.workers_per_group == {"Main": 3}


def test_tts_route_serializes_multiple_voices_to_one_worker_each():
    route = _plan_tts_voice_groups(
        "Main",
        [
            {"voice": ""},
            {"voice": "Clone A"},
            {"voice": "Clone B"},
            {"voice": "Clone A"},
        ],
        lambda value: value or "Main",
        max_workers=3,
    )

    assert route.mode == "serial"
    assert route.groups == [
        ("Main", [0]),
        ("Clone A", [1, 3]),
        ("Clone B", [2]),
    ]
    assert route.workers_per_group == {
        "Main": 1,
        "Clone A": 1,
        "Clone B": 1,
    }
