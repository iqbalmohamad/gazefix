# M3 Product Owner visual gate — SA v1.2

Status: **NOT EVALUATED**. Engineering readiness is separate from the M3
quality decision. Budget: one 45–50 minute session (capture ≈10 minutes,
score ≈35–40 minutes). No live GazeFix integration is part of this test.

## Capture once

1. Open Windows Camera or your existing recording tool at native 1280×720,
   normal lighting. Expected: an unmodified recording of your face.
2. Check readable text or a known asymmetry once. Expected: determine whether
   the saved file is mirrored; tell the engineer if it is.
3. Save four stills without glasses, looking at the lens, screen centre,
   lower-edge notes, and horizontally away by a hand's width. Expected files
   in `experiments/inputs/`: `lens-no-glasses`, `screen-no-glasses`,
   `notes-no-glasses`, `horizontal-no-glasses`, each `.png`, `.jpg` or `.jpeg`.
4. Repeat with glasses. Expected: `lens-glasses`, `screen-glasses`,
   `notes-glasses`, `horizontal-glasses` with the same supported extensions.
5. Record three 5–10 second clips while looking at screen centre: speaking
   and smiling; minor head rotation; blinks, wink, squint and closed eyes.
   Expected: `speaking-smiling.mp4`, `minor-rotation.mp4`,
   `blink-wink-squint.mp4` (AVI/MOV/MKV also supported).
6. Hand the local folder to the engineer. Expected: files stay local and ignored
   by Git; you do not run experiments or tune settings.

## Engineer prepares every artifact

From the repository root, run one command (add `--unmirror` only when the
session's saved frames were mirrored):

```powershell
.\.venv-m1-qa-r2\Scripts\python.exe -m scripts.correction_batch po --inputs experiments/inputs
```

All eleven named files are required before the batch starts. The printed
`experiments/m3-v12-po-<timestamp>/index.html` opens the sheets and clips.
Eight default-C comparison sheets, three corrected/comparison clips,
debug views, per-frame logs, settings/timings and blank `scores.csv` are
generated. Codec fallback is reported as a PNG sequence, never as a video.
If that occurs the engineer supplies a playable local rendition before scoring.
The default is strength .7 with policy, target optical axis, no smoothing.
The engineer checks measured deviation/effective strength and reports how many
captures cover the 10–20° / .5–.8 operating range. Missing coverage needs a
replacement capture, not a fabricated score. No extra B/C/tuning round unless
the PM requests one after this gate.

## Score once

1. Open each sheet at native 100% and inspect the included 3× eye crops.
   Expected: original left, corrected right, with outcomes/settings in its report.
2. Score eye realism, iris realism, blink realism where applicable, eyelid
   preservation, identity preservation, artifact visibility, and perceived eye
   contact from 1 (unacceptable) to 5 (indistinguishable from a real photo).
   Expected: eleven rows in `scores.csv`; use N/A for blink realism on ordinary stills.
3. Answer “Is correction less distracting than the original lack of eye
   contact?” for each experiment. Expected: your yes/no judgment, no computed substitute.
4. Watch the three clips at normal playback and inspect blink/wink/closed frames.
   Expected: closed-eye lids are unchanged and behavior looks natural; record
   flicker/oscillation as free-text temporal notes, not an M3 numeric score.
5. Specifically inspect moved catchlights, synthetic/flat sclera, double edges,
   lashes or glasses/glare moved with the iris, hard lid steps, and the flattened
   trailing iris edge. Expected: flag defects visible at normal size as such.
6. Return scores and qualitative comments to the PM/engineer. Expected: the
   tested SHA, settings and gate decision are recorded in `m3-evaluation.md`
   using the adjacent template; private captures/renders remain uncommitted.

The PM applies frozen SA §14.3: PROCEED, ITERATE, or CHANGE APPROACH. The
key criterion must be yes on a clear majority of operating-range experiments,
with no disqualifying artifact class; eyelid/blink/identity scores guide the
decision as specified there. **M3 is not PASS until this evaluation occurs.**
Stop after the M3 decision; M4 requires a separate assignment.
