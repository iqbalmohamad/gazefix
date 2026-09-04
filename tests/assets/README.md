# Test assets

## `astronaut_face.png`

- **Content:** a 338×307 crop (upper 60 % of the height, central 66 % of the
  width) of the colour photograph of astronaut Eileen Collins that ships as
  `skimage/data/astronaut.png` in the scikit-image 0.26.0 wheel
  (`scikit_image-0.26.0-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl`;
  original file SHA-256 `88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5`).
- **Provenance and licence (from the scikit-image `astronaut()` docstring):**
  "This image was downloaded from the NASA Great Images database
  <https://flic.kr/p/r9qvLn>. No known copyright restrictions, released into the
  public domain." NASA photograph GPN-2000-001177.
- **Crop SHA-256:** `66102c9a1f345f73cfc421fca230200045d9e8a7c3a55fdef77fdb907f814b74`
  (PNG, lossless, compression level 9).
- **Use:** the only real-face input of the opt-in real-model tests
  (`tests/test_real_model_tracking.py`) and of `scripts/tracking_test.py
  --image`. The face is only about 107 px tall at native resolution, so the
  tests scale the crop into a 1280×720 canvas (face height ≈ 190 px at the
  0.8 scale they use); this is a small, upscaled and therefore blurry face,
  not a representative webcam frame. Its detection envelope was measured
  (video mode, scale 0.7–0.9, ±200 px horizontal and ±80 px vertical
  placements: 33/33 detections) and the tests stay inside it. It cannot be
  used to characterise the detector's general minimum face size.

No webcam frames are stored in the repository.
