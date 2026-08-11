from autodub.pipeline import DubRequest


def test_dub_request_carries_mirror_choice():
    assert DubRequest(mirror=True).mirror is True
    assert DubRequest().mirror is False
