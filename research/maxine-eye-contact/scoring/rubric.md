# Product Owner scoring sheet — Maxine Phase 1A visual gate

**`RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

You will see, for each clip, up to three outputs under the neutral labels
**A**, **B** and **C**. The labels carry no meaning and **their order is
different for every clip**. One of them is the uncorrected original; the other
two are two different correction methods. Which is which is not revealed until
scoring is finished.

Score each labelled output on its own terms. Do not try to work out which
method produced it — if you find yourself doing that, score the next clip and
come back.

Open `presentation/index.html` from the package directory and fill in
`presentation/scores.csv`.

## Scores (1–5)

**5 is always the good end of the scale.**

| Column | Question | 1 | 5 |
| --- | --- | --- | --- |
| `eye_realism` | Do the eyes look like real eyes? | clearly synthetic / dead | indistinguishable from a real photo |
| `iris_realism` | Does the iris keep real texture, shape and specular detail? | flat, smeared or painted | indistinguishable from a real iris |
| `blink_realism` | Do blinks look natural, complete and correctly timed? | broken, skipped or uncanny blinks | natural blinks |
| `eyelid_preservation` | Are the eyelids and lid edges preserved without steps or warping? | lid destroyed / obvious lid-edge steps | lids untouched and natural |
| `identity_preservation` | Does the person still look like themselves? | looks like a different person | identity fully preserved |
| `temporal_stability` | Is the correction steady over time, without flicker, jitter or popping? | severe flicker / popping | completely steady |
| `artifact_visibility` | How visible are editing artifacts at normal viewing size? | obvious artifacts | no visible artifacts |
| `perceived_eye_contact` | Does the person appear to be looking at you? | clearly not looking at me | convincing eye contact |
| `overall_distraction` | Overall, how distracting is this output to watch? | very distracting | not distracting at all |

Leave a cell blank if you genuinely cannot judge it from that clip — for
instance `blink_realism` on a clip with no blink. A blank is a valid, honest
answer and is recorded as unscored. Do not guess a number to fill the sheet.

Note on `artifact_visibility` and `overall_distraction`: these two are worded so
that 5 is good, which is the same direction as every other row but the
**opposite** direction from the raw wording of the criterion. A clip full of
obvious artifacts scores **1**, not 5.

## The two questions that matter most

| Column | Question | Answers |
| --- | --- | --- |
| `less_distracting_than_original` | Is this correction less distracting than the original lack of eye contact? | `YES` / `NO` / `UNSURE` |
| `would_use_in_real_call` | Would you personally be willing to use this output in a real Zoom/Meet/Teams call? | `YES` / `NO` / `MAYBE` |

Answer these for the two corrected labels. For whichever label turns out to be
the original, answer them however feels natural or leave them blank; they will
be read against the answer key afterwards.

## Notes

Use the `notes` column freely. Specific observations — "the left eye pops on
the blink", "looks fine until the head turns" — are worth more than the numbers
for deciding what happens next.

## The verdict

After scoring every clip, and only then, open the answer key. Then give exactly
one verdict for the whole gate:

- **`PASS`** — Maxine is clearly and materially more natural than the geometric
  baseline **and** you would genuinely consider using the result in a real
  video call. This authorizes nothing on its own; it lets the Product Manager
  consider a future realtime/cloud feasibility stage.

- **`ITERATE`** — the visual upside is clearly substantial, but a specific,
  objective flaw in *this test* prevents a fair conclusion. Name the flaw. This
  is not an invitation to open-ended visual tuning, and any iteration needs
  separate authorization.

- **`CHANGE APPROACH`** — Maxine is still uncanny or distracting, the
  improvement over the geometric baseline is not material, the eye-contact
  effect is weak, artifacts / identity / blink / lid behaviour remain
  unacceptable, or you would not use it in a real call. This stops the Maxine
  cloud path.

Record the verdict, the scores and your reasoning in a milestone document under
`docs/milestones/`, in the manner of `docs/milestones/m3-evaluation.md`. State
plainly which scenarios the evidence did **not** cover, so the record does not
imply more than it establishes.

## Session budget

Per `docs/qa-policy.md` §9 this should be a single, short, batched session. With
three clips at three conditions it is roughly 10–15 minutes; a fuller 6–10 clip
set is longer and should be agreed with the Product Manager before it starts.
