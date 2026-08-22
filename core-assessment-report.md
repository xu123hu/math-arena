# Core assessment remediation B report

## Scope and controller ruling

The quiz controller now treats `count` as the publication gate and type quotas
as an auditable supply plan. When quotas are under-specified, the remainder is
allocated round-robin only across explicitly requested types. When quotas exceed
`count`, the request returns `422 / 40001 / question_type_quota_exceeds_count`.
This is the smallest compatible choice for existing callers: the teacher UI and
capability handler already send exact totals, while legacy/all-zero callers get
the deterministic `text=count` fallback. The error cost is intentional: a
teacher must correct an impossible over-quota request rather than receive an
apparently sufficient paper with one requested type silently removed.

`Artifact.validation` preserves requested and effective type distributions,
normalization state, expanded allowed KP codes, requested difficulty mix, and
per type/difficulty-slot requested/fulfilled/relaxed counts.

## RED / GREEN evidence

- RED: assessment tests failed for under-quota truncation, over-quota acceptance,
  missing difficulty-slot audit, and incomplete choice rows being retained.
- GREEN backend: `pytest tests/test_m3_teacher_assessment.py tests/test_question_supply.py -q`
  passed 21 tests; targeted assessment run passed 10 tests; scoped Ruff passed.
- RED frontend: preview import failed before the mapper existed; mock contract
  lacked type-distribution validation.
- GREEN frontend: focused preview/mock tests passed 3 tests; full Vitest passed
  56 tests; `vue-tsc --noEmit`, production build, and `E2E_PORT=5186` teacher
  mock E2E all passed (6 tests).

## Delivered behavior

- Strict requested-subtree supply, without parent/sibling widening; joint-KP
  artifacts choose an in-scope matched `kp_code`, never the unrelated first tag.
- Exact difficulty is supplied per type/difficulty slot, relaxing only within
  the same strict KP/type and recording the relaxation warning.
- Empty-answer questions and choice rows with unusable options are excluded from
  both the Artifact and `available_count`; missing analysis remains editable
  with an explicit teacher warning and fallback text.
- Frontend types, preview, mock server, and E2E accept object/array options,
  `solution` compatibility, standard answers, analysis, difficulty, and
  validation slot data. Blank/solution previews have no invented option list.

## Scoped commits

- Backend: `fix(m3): enforce auditable quiz fulfillment`
- Frontend: `fix(m3): preview complete quiz artifacts`

## Self-review and residual risk

No router, Butler, layout, or global-style files changed. `row_filter` loads
the strict candidate set before selecting publishable rows so malformed rows
cannot hide usable inventory; for unusually large bank subsets this is a
deliberate correctness-over-query-limit trade-off and should be monitored with
production inventory volume.
