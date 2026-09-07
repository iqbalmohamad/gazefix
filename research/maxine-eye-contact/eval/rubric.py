"""Product Owner scoring rubric for the Phase 1A visual gate (S13).

The nine 1-5 dimensions and the two closing questions come from the Phase 1A
assignment. Their wording deliberately matches the M3 gate record
(``docs/milestones/m3-evaluation.md``) wherever the two overlap, so a Phase 1A
score is directly comparable with the M3 scores the Product Owner already gave
the geometric baseline.

Nothing in this module assigns or infers a score. The engineer does not hold
the visual verdict.
"""

from __future__ import annotations

SCALE_MIN = 1
SCALE_MAX = 5

#: 1-5 dimensions, in assignment order. ``high_is_good`` records the direction
#: of the scale so a reader cannot mistake "artifact visibility 1" for good.
DIMENSIONS = (
    {"key": "eye_realism", "title": "Eye realism",
     "prompt": "Do the eyes look like real eyes?",
     "low": "1 = clearly synthetic / dead",
     "high": "5 = indistinguishable from a real photo",
     "high_is_good": True},
    {"key": "iris_realism", "title": "Iris realism",
     "prompt": "Does the iris keep real texture, shape and specular detail?",
     "low": "1 = flat, smeared or painted",
     "high": "5 = indistinguishable from a real iris",
     "high_is_good": True},
    {"key": "blink_realism", "title": "Blink realism",
     "prompt": "Do blinks look natural, complete and correctly timed?",
     "low": "1 = broken, skipped or uncanny blinks",
     "high": "5 = natural blinks",
     "high_is_good": True},
    {"key": "eyelid_preservation", "title": "Eyelid preservation",
     "prompt": "Are the eyelids and lid edges preserved without steps or warping?",
     "low": "1 = lid destroyed / obvious lid-edge steps",
     "high": "5 = lids untouched and natural",
     "high_is_good": True},
    {"key": "identity_preservation", "title": "Identity preservation",
     "prompt": "Does the person still look like themselves?",
     "low": "1 = looks like a different person",
     "high": "5 = identity fully preserved",
     "high_is_good": True},
    {"key": "temporal_stability", "title": "Temporal stability",
     "prompt": "Is the correction steady over time, without flicker, jitter or popping?",
     "low": "1 = severe flicker / popping",
     "high": "5 = completely steady",
     "high_is_good": True},
    {"key": "artifact_visibility", "title": "Artifact visibility",
     "prompt": "How visible are editing artifacts at normal viewing size?",
     "low": "1 = obvious artifacts",
     "high": "5 = no visible artifacts",
     "high_is_good": True},
    {"key": "perceived_eye_contact", "title": "Perceived eye contact",
     "prompt": "Does the person appear to be looking at you?",
     "low": "1 = clearly not looking at me",
     "high": "5 = convincing eye contact",
     "high_is_good": True},
    {"key": "overall_distraction", "title": "Overall distraction",
     "prompt": "Overall, how distracting is this output to watch?",
     "low": "1 = very distracting",
     "high": "5 = not distracting at all",
     "high_is_good": True},
)

DIMENSION_KEYS = tuple(d["key"] for d in DIMENSIONS)

#: Closing questions, in assignment order.
QUESTIONS = (
    {"key": "less_distracting_than_original",
     "prompt": "Is this correction less distracting than the original lack of "
               "eye contact?",
     "choices": ("YES", "NO", "UNSURE")},
    {"key": "would_use_in_real_call",
     "prompt": "Would you personally be willing to use this output in a real "
               "Zoom/Meet/Teams call?",
     "choices": ("YES", "NO", "MAYBE")},
)

QUESTION_KEYS = tuple(q["key"] for q in QUESTIONS)

FREE_TEXT = ("notes",)

#: The columns of the scoring sheet, in order.
COLUMNS = ("clip_id", "label") + DIMENSION_KEYS + QUESTION_KEYS + FREE_TEXT

#: The Phase 1A verdicts. The Product Owner assigns exactly one, for the whole
#: gate; the implementing engineer never does.
VERDICTS = ("PASS", "ITERATE", "CHANGE APPROACH")


def validate_score(key, value):
    """Validate one 1-5 dimension score. Blank means unscored, which is valid."""
    if key not in DIMENSION_KEYS:
        raise KeyError(f"unknown dimension: {key}")
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key}: score must be an integer {SCALE_MIN}-{SCALE_MAX}")
    try:
        # A fractional score must be rejected, not silently truncated: int(2.5)
        # would quietly record 2 and misstate what the Product Owner wrote.
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{key}: score must be an integer {SCALE_MIN}-{SCALE_MAX}") from None
    if not SCALE_MIN <= number <= SCALE_MAX:
        raise ValueError(f"{key}: score must be {SCALE_MIN}-{SCALE_MAX}, got {number}")
    return number


def validate_answer(key, value):
    """Validate one closing-question answer. Blank means unanswered."""
    question = next((q for q in QUESTIONS if q["key"] == key), None)
    if question is None:
        raise KeyError(f"unknown question: {key}")
    if value in (None, ""):
        return None
    answer = str(value).strip().upper()
    if answer not in question["choices"]:
        raise ValueError(f"{key}: must be one of {', '.join(question['choices'])}, "
                         f"got {value!r}")
    return answer


def blank_row(clip_id, label):
    """A blank scoring row for one clip under one neutral label."""
    row = {"clip_id": clip_id, "label": label}
    row.update({k: "" for k in DIMENSION_KEYS})
    row.update({k: "" for k in QUESTION_KEYS})
    row.update({k: "" for k in FREE_TEXT})
    return row


def validate_sheet(rows):
    """Validate a filled scoring sheet, returning ``(clean, errors)``."""
    clean, errors = [], []
    for index, row in enumerate(rows, start=1):
        where = f"row {index} ({row.get('clip_id')}/{row.get('label')})"
        entry = {"clip_id": row.get("clip_id"), "label": row.get("label")}
        for key in DIMENSION_KEYS:
            try:
                entry[key] = validate_score(key, row.get(key))
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                entry[key] = None
        for key in QUESTION_KEYS:
            try:
                entry[key] = validate_answer(key, row.get(key))
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                entry[key] = None
        entry["notes"] = row.get("notes") or ""
        clean.append(entry)
    return clean, errors
