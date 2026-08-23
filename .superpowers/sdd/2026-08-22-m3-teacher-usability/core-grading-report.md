# Core grading remediation C report

## Scope

- Assignment missing or soft-deleted now terminates grading detail, suggestion, and file reads with the existing `40400/not_found` privacy response before answer or file access.
- Persisted grading context is trusted only when exactly one non-deleted `QuizItem` matches both `item_no` and `q_type`.
- An objective suggestion whose context later becomes missing, ambiguous, or type-mismatched is rendered as review-needed with zero confidence and explicit evidence; its historical suggested score is withheld from detail. Confirmed final scores are not changed.
- Confirmation still permits an authorized teacher to record a final score, but mastery updates use the same trusted-context lookup and therefore skip missing, ambiguous, or mismatched items. Unique trusted context continues to update the corresponding knowledge point.

## TDD evidence

The new regression tests were first run against `12486333ddd2b0416bfbb29f8af585272aa1332a` and failed for the intended defects: orphan/soft-deleted grading endpoints returned `200`, stale duplicate-context suggestions remained high confidence, q-type mismatch auto-scored from the standard answer, and duplicate confirmation created mastery. The mastery fixture's initial overlength knowledge-point code was corrected before re-running RED; it then failed because an arbitrary duplicate `QuizItem` updated mastery.

## Verification

- `pytest tests/test_m3_teacher_grading.py tests/test_m3_teacher_scope.py tests/test_m3_fullstack_closure.py -q` — 33 passed.
- `pytest (Get-ChildItem tests -Filter 'test_m3_teacher_*.py' | ForEach-Object { $_.FullName }) tests\test_m3_fullstack_closure.py -q` — 110 passed.
- `ruff check app/domains/teacher/grading.py tests/test_m3_teacher_grading.py` — passed.
- `git diff --check` — passed.
