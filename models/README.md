# Model assets

GazeFix M1 uses exactly one pretrained model, the MediaPipe **Face Landmarker**
task bundle. It is **not** stored in this repository and the application
**never downloads it at runtime**; it is installed once by an explicit command
and read offline from the per-user model directory afterwards.

| Field | Value |
| --- | --- |
| File | `face_landmarker.task` |
| Official source | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` |
| Release | `face_landmarker/float16/1` (identical bytes are published under `float16/latest`), object last modified 2023-05-03 |
| Size | 3,758,596 bytes |
| SHA-256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| MD5 (storage ETag) | `b0e7274907a1644404fef66b28dd6d85` |
| Contents (zip bundle) | `face_detector.tflite` (BlazeFace short-range), `face_landmarks_detector.tflite` (Face Mesh V2 with attention: 468 mesh + 10 iris points), `face_blendshapes.tflite` (not executed by GazeFix), `geometry_pipeline_metadata_landmarks.binarypb` (canonical face geometry for the head-pose matrix) |
| Model licence | Apache License, Version 2.0 — stated on the model cards "MediaPipe BlazeFace Model Card (Short Range)", "Model Card MediaPipe Face Mesh V2" and "Model Card Blendshape V2" (Google, `mediapipe-assets` storage) |
| Code licence of the runtime (`mediapipe` 1.0.1) | Apache-2.0 |
| Redistribution | Apache-2.0 permits redistribution with attribution and licence notice; GazeFix nevertheless does not vendor the file so that provenance is always the official source |

## Local location

Default: `%LOCALAPPDATA%\GazeFix\models\face_landmarker.task` on Windows
(`~/.local/state/GazeFix/models/` elsewhere). Override with `--model-dir` on
`gazefix`, `scripts/fetch_model.py` and `scripts/tracking_test.py`.

## Setup (one-time, explicit)

```powershell
.venv\Scripts\python scripts\fetch_model.py
```

The command downloads to a temporary file in the model directory, verifies
size and SHA-256, and only then moves the file into place; a failed or
interrupted download leaves nothing behind. It prints one JSON object and
exits 0 when the model is verified, 1 otherwise. `--verify-only` reports the
state without touching the network; `--force` re-downloads.

At every tracker start the application re-verifies size and SHA-256 (a few
milliseconds). A missing, truncated, or different file is reported in the
status line and log as an actionable error naming this command, and the
original camera preview keeps running without tracking.
