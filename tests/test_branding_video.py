from autodub.media.video import branding_region


def test_branding_region_falls_back_to_top_right():
    region = branding_region(None)
    assert region["x"] == 0.76
    assert region["y"] == 0.04
    assert region["w"] == 0.2


def test_branding_region_clamps_custom_values():
    region = branding_region({"x": 0.9, "y": -1, "w": 0.5, "h": 0.5})
    assert region == {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5}
