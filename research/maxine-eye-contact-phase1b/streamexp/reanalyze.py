"""Re-evaluate a finished Stage A run offline, without contacting Maxine.

A Stage A run is expensive: it needs a provisioned GPU host and it spends real
time. When the *decoder* semantics improve — as they did once a metadata-only
prefix turned out to be classifiable rather than ambiguous — the run should not
have to be repeated to get the better answer. Everything needed is already on
disk.

What this recomputes: only what a decoder or an audit produces — the pre-EOS
determination, the decode status and frame count, and the parser-versus-decoder
comparison.

What this never does: touch RPC timing. Arrival instants and the input-EOS
instant are read from the completed run and carried forward verbatim; they are
measurements of an event that has already happened and cannot be improved by
re-reading a file. Nor does it contact the service, regenerate output, or
overwrite anything. The original ``summary.json`` is left exactly as the run
wrote it and its digest is recorded, so an amended answer can always be traced
back to the evidence it came from.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from . import decode
from .session import first_at_or_after, select_boundary

#: Bumped when the meaning of a recomputed field changes, so two reanalysis
#: artifacts of the same run are comparable.
REANALYSIS_VERSION = 1

NOT_RECOMPUTED = (
    "RPC start, per-chunk arrival instants, input EOS, send timings, backlog "
    "series, schedule lateness, throughput, and every byte of the corrected "
    "output — all carried forward from the original run unchanged.",
)


class ReanalysisError(RuntimeError):
    """The run directory does not hold what an offline re-analysis needs."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_chunks(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                rows.append(
                    {
                        "t_ms": float(row["t_ms"]),
                        "bytes": int(row["bytes"]),
                        "cumulative_bytes": int(row["cumulative_bytes"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def reanalyze_stage_a(run_dir: Path) -> dict[str, Any]:
    """Recompute the decoder-backed parts of a completed Stage A run."""
    run_dir = run_dir.expanduser().resolve()
    summary_path = run_dir / "summary.json"
    corrected = run_dir / "corrected.mp4"
    if not summary_path.is_file():
        raise ReanalysisError(f"no summary.json in {run_dir}")
    if not corrected.is_file():
        raise ReanalysisError(f"no corrected.mp4 in {run_dir}")

    original = json.loads(summary_path.read_text(encoding="utf-8"))
    original_pre_eos = original.get("pre_eos_evidence", {}) or {}
    eos_ms = original_pre_eos.get("input_eos_ms")
    if not isinstance(eos_ms, (int, float)):
        # Older runs recorded EOS only in the timing block.
        elapsed = (original.get("timing_ms_since_rpc_start", {}) or {}).get("input_eos_ms")
        eos_ms = elapsed if isinstance(elapsed, (int, float)) else None

    boundary = _recompute_boundary(run_dir, original_pre_eos, eos_ms)
    pre_eos = _reexamine_pre_eos(run_dir, corrected, boundary, eos_ms)
    audit = _reaudit_full_output(corrected, original)

    original_determination = (original.get("determinations", {}) or {}).get(
        "usable_output_before_input_eos", "UNKNOWN"
    )
    return {
        "reanalysis_version": REANALYSIS_VERSION,
        "what_this_is": (
            "An offline re-evaluation of a completed Stage A run. Only "
            "decoder-backed and audit-derived fields are recomputed; the RPC "
            "measurements are carried forward from the original run unchanged. "
            "Maxine was not contacted."
        ),
        "run_dir": str(run_dir),
        "original_summary": {
            "path": str(summary_path),
            "sha256": _sha256(summary_path),
            "preserved": True,
        },
        "carried_forward_unchanged": {
            "input_eos_ms": eos_ms if eos_ms is not None else "NOT MEASURED",
            "timing_ms_since_rpc_start": original.get("timing_ms_since_rpc_start", {}),
            "note": (
                "these are measurements of events that already happened and are "
                "not recomputed by this tool"
            ),
        },
        "recomputed_boundary": boundary,
        "pre_eos_evidence": pre_eos,
        "full_output_audit": audit,
        "determination": {
            "original": original_determination,
            "reanalysed": pre_eos["determination"],
            "changed": original_determination != pre_eos["determination"],
            "basis": "independent decoder on the exact pre-EOS prefix",
        },
        "not_recomputed": list(NOT_RECOMPUTED),
    }


def _recompute_boundary(
    run_dir: Path, original_pre_eos: dict[str, Any], eos_ms: float | None
) -> dict[str, Any]:
    """Re-derive the pre-EOS cut from the per-chunk log, and check it agrees."""
    saved = original_pre_eos.get("cumulative_bytes")
    saved_bytes = saved if isinstance(saved, int) else None
    chunks_path = run_dir / "response_chunks.csv"

    if eos_ms is None:
        return {
            "source": "none — the original run recorded no input EOS instant",
            "cumulative_bytes": "NOT MEASURED",
            "cutoff_time_ms": "NOT MEASURED",
            "agrees_with_original": "NOT MEASURED",
        }
    if not chunks_path.is_file():
        return {
            "source": "original summary — response_chunks.csv is absent",
            "cumulative_bytes": saved_bytes if saved_bytes is not None else "NOT MEASURED",
            "cutoff_time_ms": original_pre_eos.get("cutoff_time_ms", "NOT MEASURED"),
            "agrees_with_original": True,
            "note": (
                "the boundary could not be independently re-derived; it is taken "
                "from the original run rather than invented"
            ),
        }

    rows = _load_chunks(chunks_path)
    cumulative, arrival = select_boundary(rows, eos_ms)
    following = first_at_or_after(rows, eos_ms)
    return {
        "source": "response_chunks.csv, re-derived",
        "media_chunks_total": len(rows),
        "media_chunks_before_eos": sum(1 for r in rows if r["t_ms"] < eos_ms),
        "cutoff_time_ms": arrival if arrival is not None else "NONE — no media arrived before EOS",
        "cumulative_bytes": cumulative,
        "first_chunk_at_or_after_eos": following or "none",
        "gap_to_eos_ms": round(eos_ms - arrival, 4) if arrival is not None else "NOT MEASURED",
        "original_cumulative_bytes": saved_bytes if saved_bytes is not None else "not recorded",
        "agrees_with_original": (saved_bytes is None or saved_bytes == cumulative),
    }


def _reexamine_pre_eos(
    run_dir: Path, corrected: Path, boundary: dict[str, Any], eos_ms: float | None
) -> dict[str, Any]:
    """Re-cut the prefix from the saved output and re-examine it with a decoder."""
    cumulative = boundary.get("cumulative_bytes")
    if not isinstance(cumulative, int):
        return {
            "determination": "NOT MEASURED",
            "reason": "the pre-EOS boundary could not be established from the saved run",
            "cutoff_time_ms": boundary.get("cutoff_time_ms", "NOT MEASURED"),
            "cumulative_bytes": "NOT MEASURED",
            "ffprobe_stream_detected": "NOT MEASURED",
            "frames_decoded": "NOT MEASURED",
            "decode_status": "NOT MEASURED",
        }
    if cumulative == 0:
        return {
            "determination": "NO",
            "reason": (
                "no media byte at all had arrived when the client finished sending; "
                "no decoder is needed to conclude that no corrected frame was usable"
            ),
            "cutoff_time_ms": boundary.get("cutoff_time_ms"),
            "cumulative_bytes": 0,
            "ffprobe_stream_detected": False,
            "frames_decoded": 0,
            "decode_status": "NOT ATTEMPTED — there were no bytes to examine",
        }

    # Written under a distinct name: the original prefix is evidence and is never
    # overwritten, even when the two are byte-identical.
    rebuilt = run_dir / "pre_eos_corrected.reanalysis.mp4"
    rebuilt.write_bytes(corrected.read_bytes()[:cumulative])

    saved_prefix = run_dir / "pre_eos_corrected.mp4"
    matches_saved: Any = "no saved prefix to compare"
    if saved_prefix.is_file():
        matches_saved = _sha256(saved_prefix) == _sha256(rebuilt)

    exam = decode.examine(rebuilt)
    if exam.status == "VERIFIED":
        determination, reason = "YES", (
            f"{exam.frames_decoded} corrected frame(s) decode from the exact bytes "
            "the client held before it finished sending"
        )
    elif exam.status == "EMPTY":
        determination, reason = "NO", (
            "a decoder recognised the container, walked it to EOF and found no "
            "complete frame in the exact pre-EOS prefix"
        )
    else:
        determination, reason = "NOT MEASURED", (
            "the decoder could not examine the prefix; a tool failure is not a NO"
        )

    return {
        "determination": determination,
        "reason": reason,
        "input_eos_ms": eos_ms,
        "cutoff_time_ms": boundary.get("cutoff_time_ms"),
        "cumulative_bytes": cumulative,
        "ffprobe_stream_detected": exam.stream_detected,
        "frames_decoded": exam.frames_decoded if exam.frames_decoded is not None else "UNKNOWN",
        "decode_status": exam.status,
        "decoder_detail": exam.detail,
        "artifact": str(rebuilt),
        "matches_saved_pre_eos_prefix": matches_saved,
    }


def _reaudit_full_output(corrected: Path, original: dict[str, Any]) -> dict[str, Any]:
    """Recount the complete output and re-check the progressive parser against it."""
    parser_frames = (original.get("full_output_audit", {}) or {}).get("parser_frames")
    if not isinstance(parser_frames, int):
        parser_frames = (original.get("throughput", {}) or {}).get("usable_output_frames")
    exam = decode.examine(corrected)
    if not exam.determinate or exam.frames_decoded is None:
        return {
            "decoder_frames": "NOT MEASURED",
            "parser_frames": parser_frames if isinstance(parser_frames, int) else "unknown",
            "agreement": "NOT MEASURED",
            "parser_trusted": False,
            "decode_status": exam.status,
            "decoder_detail": exam.detail,
        }
    agree = isinstance(parser_frames, int) and exam.frames_decoded == parser_frames
    return {
        "decoder_frames": exam.frames_decoded,
        "parser_frames": parser_frames if isinstance(parser_frames, int) else "unknown",
        "agreement": "AGREE" if agree else "DISAGREE",
        "parser_trusted": agree,
        "decode_status": exam.status,
        "decoder_detail": exam.detail,
        "note": (
            "the progressive parser's count matches an independent decoder"
            if agree else
            "the progressive parser's count is contradicted by an independent "
            "decoder; its correspondence and per-frame ages remain withdrawn"
        ),
    }


def write_reanalysis(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Run the re-analysis and write ``reanalysis.json`` beside the original."""
    payload = reanalyze_stage_a(run_dir)
    out = Path(payload["run_dir"]) / "reanalysis.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["artifact"] = str(out)
    return out, payload
