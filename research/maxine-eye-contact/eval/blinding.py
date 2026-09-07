"""Deterministic blinding of the two correction conditions (S12).

The Product Owner must not know which corrected output is geometric and which
is Maxine while scoring. Blinding is deterministic from a recorded seed, so the
assignment is reproducible and auditable after the fact, and cannot be quietly
reshuffled once results are seen.

``ORIGINAL`` is presented under a neutral label too, but it is not required to
be indistinguishable: a viewer can usually tell an uncorrected clip. What must
be blinded is which of the two *corrections* is which.
"""

from __future__ import annotations

import hashlib
import random

#: Neutral presentation labels, in presentation order.
LABELS = ("A", "B", "C")

ORIGINAL = "ORIGINAL"
GEOMETRIC = "GEOMETRIC"
MAXINE = "MAXINE"

#: The two conditions whose identity must be hidden from the scorer.
BLINDED_CONDITIONS = (GEOMETRIC, MAXINE)
CONDITIONS = (ORIGINAL, GEOMETRIC, MAXINE)


def _stream(seed, clip_id):
    """A per-clip deterministic RNG derived from the recorded seed.

    Deriving per clip (rather than drawing from one running stream) means a
    clip's assignment does not depend on how many clips precede it, so adding
    or excluding a clip cannot silently re-roll the others.
    """
    material = f"{seed}\x1f{clip_id}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest, "big"))


def assign(seed, clip_id, conditions=CONDITIONS):
    """Return ``{label: condition}`` for one clip.

    ``ORIGINAL`` takes part in the label shuffle so its label is not a constant
    that would leak the other two by elimination.
    """
    conditions = list(conditions)
    if not conditions:
        raise ValueError("at least one condition is required")
    if len(conditions) > len(LABELS):
        raise ValueError(f"at most {len(LABELS)} conditions are supported")
    if len(set(conditions)) != len(conditions):
        raise ValueError("conditions must be unique")
    order = list(conditions)
    _stream(seed, clip_id).shuffle(order)
    return {label: condition for label, condition in zip(LABELS, order)}


def answer_key(seed, clips):
    """Build the full answer key: clip id to label-condition mapping.

    ``clips`` is an iterable of ``(clip_id, conditions)`` pairs, where
    ``conditions`` is the subset actually available for that clip.
    """
    rows = []
    for clip_id, conditions in clips:
        mapping = assign(seed, clip_id, conditions)
        rows.append({
            "clip_id": clip_id,
            "labels": mapping,
            "reverse": {condition: label for label, condition in mapping.items()},
        })
    return {"seed": seed, "label_vocabulary": list(LABELS), "clips": rows}


def label_for(key, clip_id, condition):
    """Look up the neutral label a condition was presented under."""
    for row in key["clips"]:
        if row["clip_id"] == clip_id:
            label = row["reverse"].get(condition)
            if label is None:
                raise KeyError(f"{clip_id}: condition not present: {condition}")
            return label
    raise KeyError(f"unknown clip_id: {clip_id}")


def condition_for(key, clip_id, label):
    """Look up which condition a neutral label refers to."""
    for row in key["clips"]:
        if row["clip_id"] == clip_id:
            condition = row["labels"].get(label)
            if condition is None:
                raise KeyError(f"{clip_id}: label not used: {label}")
            return condition
    raise KeyError(f"unknown clip_id: {clip_id}")


#: Tokens that would tell the scorer which method produced an output. The
#: subject of the gate ("eye contact") is deliberately NOT a leak token: the
#: Product Owner knows what is being evaluated, and the rubric legitimately
#: contains a ``perceived_eye_contact`` column. What must stay hidden is which
#: of the two corrections is which.
LEAK_TOKENS = ("GEOMETRIC", "MAXINE", "NVIDIA", "NVCF", "BASELINE", "M3-")


def leaks(text):
    """Return method-identifying tokens that appear in scorer-facing text.

    A blind package must never name GEOMETRIC or MAXINE where the scorer can
    read it. Used by the integrity check over the presentation directory.
    """
    haystack = str(text).upper()
    return [token for token in LEAK_TOKENS if token in haystack]


#: Below this many clips, a condition occupying one label is unavoidable rather
#: than a defect, so the pinning check does not apply.
MIN_CLIPS_FOR_PINNING_CHECK = 3


def pinned_conditions(assignments):
    """Conditions that occupy exactly one label across every clip.

    A deterministic shuffle can still, by chance, place one condition under the
    same neutral label in every clip. That is a weak blind: a scorer who
    notices the pattern can start scoring the method rather than the output.
    ``assignments`` is an iterable of ``{label: condition}`` mappings, one per
    clip. The seed is chosen and recorded before any output is inspected, so
    re-rolling on this signal biases nothing.
    """
    assignments = list(assignments)
    if len(assignments) < MIN_CLIPS_FOR_PINNING_CHECK:
        return []
    labels_by_condition = {}
    for mapping in assignments:
        for label, condition in mapping.items():
            labels_by_condition.setdefault(condition, set()).add(label)
    return sorted(condition for condition, labels in labels_by_condition.items()
                  if len(labels) == 1)


def suggest_seed(seed, assignments_for):
    """Return the first seed of the form ``<seed>-<n>`` with no pinned condition.

    ``assignments_for(seed)`` returns the per-clip mappings for a candidate
    seed. Returns ``None`` if no nearby seed works, which cannot happen for a
    realistic clip count but is reported rather than looped on forever.
    """
    for suffix in range(1, 100):
        candidate = f"{seed}-{suffix}"
        if not pinned_conditions(assignments_for(candidate)):
            return candidate
    return None
