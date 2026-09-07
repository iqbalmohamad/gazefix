"""Canonical scenario coverage for the Phase 1A held-out set.

The eight scenarios required by the Phase 1A assignment are mapped onto the
capture vocabulary the frozen M3 evaluation already established in
``scripts/correction_batch.py`` (stills ``{lens,screen,notes,horizontal}`` x
``{no-glasses,glasses}``; clips ``speaking-smiling``, ``minor-rotation``,
``blink-wink-squint``). Reusing that vocabulary keeps a Phase 1A clip
traceable to the M3 capture it came from.

Nothing here manufactures a missing condition. A scenario with no source
material is reported as NOT_AVAILABLE, never substituted.
"""

from __future__ import annotations

NOT_AVAILABLE = "NOT AVAILABLE IN EXISTING SOURCE MATERIAL"

#: Assignment-required scenarios, in assignment order. ``m3_stems`` lists the
#: M3 capture stems whose recorded condition satisfies the scenario.
SCENARIOS = (
    {
        "id": "near-normal-gaze",
        "title": "Near-normal gaze",
        "description": "Subject looking at or very close to the camera lens.",
        "m3_stems": ("lens-no-glasses", "lens-glasses"),
    },
    {
        "id": "horizontal-deviation",
        "title": "Horizontal gaze deviation",
        "description": "Subject's gaze displaced left or right of the lens.",
        "m3_stems": ("horizontal-no-glasses", "horizontal-glasses"),
    },
    {
        "id": "downward-read",
        "title": "Downward / read-like gaze",
        "description": "Subject reading a screen or notes below the lens.",
        "m3_stems": ("screen-no-glasses", "screen-glasses",
                     "notes-no-glasses", "notes-glasses"),
    },
    {
        "id": "natural-speaking",
        "title": "Natural speaking",
        "description": "Subject talking naturally, mouth and face in motion.",
        "m3_stems": ("speaking-smiling",),
    },
    {
        "id": "blink",
        "title": "Blink",
        "description": "Subject blinking, winking or squinting.",
        "m3_stems": ("blink-wink-squint",),
    },
    {
        "id": "small-head-movement",
        "title": "Small head movement",
        "description": "Subject rotating or translating the head slightly.",
        "m3_stems": ("minor-rotation",),
    },
    {
        "id": "glasses",
        "title": "Glasses",
        "description": "Subject wearing glasses. Only if existing footage has it.",
        "m3_stems": ("lens-glasses", "screen-glasses",
                     "notes-glasses", "horizontal-glasses"),
    },
    {
        "id": "no-glasses",
        "title": "No glasses",
        "description": "Subject not wearing glasses.",
        "m3_stems": ("lens-no-glasses", "screen-no-glasses",
                     "notes-no-glasses", "horizontal-no-glasses"),
    },
)

SCENARIO_IDS = tuple(s["id"] for s in SCENARIOS)

#: M3 capture stems that are *clips* rather than stills. Maxine Eye Contact is
#: a temporal video model, so a still is not a usable held-out input for it.
M3_CLIP_STEMS = ("speaking-smiling", "minor-rotation", "blink-wink-squint")

#: M3 capture stems that were captured as stills.
M3_STILL_STEMS = tuple(
    f"{gaze}-{glasses}"
    for glasses in ("no-glasses", "glasses")
    for gaze in ("lens", "screen", "notes", "horizontal")
)


def scenario(scenario_id):
    """Return the scenario record for ``scenario_id``."""
    for record in SCENARIOS:
        if record["id"] == scenario_id:
            return record
    raise KeyError(f"unknown scenario: {scenario_id}")


def scenarios_for_stem(stem):
    """Return the scenario ids an M3 capture stem satisfies, in order."""
    return tuple(s["id"] for s in SCENARIOS if stem in s["m3_stems"])


def coverage(clips):
    """Map every required scenario to the clip ids covering it.

    ``clips`` is an iterable of mappings with ``clip_id`` and ``scenarios``
    keys. A scenario with no clip is reported with ``status`` NOT_AVAILABLE and
    an empty clip list; it is never back-filled.
    """
    clips = list(clips)
    report = []
    for record in SCENARIOS:
        covering = [c["clip_id"] for c in clips
                    if record["id"] in tuple(c.get("scenarios") or ())]
        report.append({
            "scenario": record["id"],
            "title": record["title"],
            "clip_ids": covering,
            "status": "COVERED" if covering else NOT_AVAILABLE,
        })
    return report


def uncovered(clips):
    """Return the ids of required scenarios no clip covers."""
    return tuple(row["scenario"] for row in coverage(clips)
                 if row["status"] == NOT_AVAILABLE)
