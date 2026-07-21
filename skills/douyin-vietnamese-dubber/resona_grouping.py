"""Pure, report-safe grouping metadata for short Resona TTS units."""
from dialogue_boundary import boundary_after


def _join_piece(text):
    text = " ".join(str(text or "").split())
    if text and text[-1] not in ".!?…。！？":
        text += "."
    return text


def ordered_source_cue_ids(group):
    """Return source entry ordinals carried with each parsed cue."""
    return [item[3] for item in group]


def group_resona_entries(entries, source_cue_ids=None, *, min_chars, max_chars, max_cues,
                         hard_max_duration_ms, max_internal_gap_ms):
    """Group short adjacent entries while retaining ordered original cue identity."""
    if source_cue_ids is not None:
        entries = [(*entry, source_cue_ids[index]) for index, entry in enumerate(entries)]
    grouped, metadata, index = [], {}, 0
    while index < len(entries):
        group = [entries[index]]
        while index + len(group) < len(entries):
            next_entry = entries[index + len(group)]
            if (next_entry[0] - group[-1][1] > max_internal_gap_ms
                    or boundary_after(group[-1][2])
                    or len(group) >= max_cues
                    or next_entry[1] - group[0][0] > hard_max_duration_ms):
                break
            preview = " ".join(_join_piece(item[2]) for item in group + [next_entry] if _join_piece(item[2]))
            if len(preview) > max_chars:
                break
            group.append(next_entry)
            if len(preview) >= min_chars:
                break
        text = " ".join(_join_piece(item[2]) for item in group if _join_piece(item[2]))
        if len(group) > 1 and len(text) >= min_chars:
            grouped.append((group[0][0], group[-1][1], text))
            group_index = len(grouped)
            metadata[group_index] = {
                "group_index": group_index,
                "source_segment_count": len(group),
                "source_cue_ids": ordered_source_cue_ids(group),
                "source_start_ms": group[0][0],
                "source_end_ms": group[-1][1],
            }
            index += len(group)
        else:
            grouped.append(entries[index][:3])
            index += 1
    return grouped, metadata
