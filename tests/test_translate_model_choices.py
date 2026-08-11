from autodub_gui.pages.translate_tool_page import model_choices


def test_custom_model_stays_first_when_endpoint_does_not_list_it():
    assert model_choices(
        ["a", "b"], "oc/deepseek-v4-flash-free(max)"
    ) == ["oc/deepseek-v4-flash-free(max)", "a", "b"]


def test_saved_model_moves_first_without_duplicates():
    assert model_choices(["a", "b"], "b") == ["b", "a"]


def test_blank_saved_model_keeps_endpoint_order():
    assert model_choices(["a", "b"], "") == ["a", "b"]
