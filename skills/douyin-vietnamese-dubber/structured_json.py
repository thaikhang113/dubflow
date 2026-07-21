"""Strict extraction of one complete JSON object from model output."""
import json


def extract_first_json_object(text):
    """Return the first complete object found by decoding, never by repairing text."""
    raw = str(text or "")
    if not raw.strip():
        raise json.JSONDecodeError("No JSON object found", raw, 0)

    decoder = json.JSONDecoder()
    object_depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            continue
        if character == "{":
            if object_depth == 0:
                try:
                    value, _ = decoder.raw_decode(raw, index)
                except json.JSONDecodeError:
                    object_depth = 1
                    continue
                if isinstance(value, dict):
                    return value
            object_depth += 1
        elif character == "}" and object_depth:
            object_depth -= 1

    raise json.JSONDecodeError("No complete JSON object found", raw, 0)
