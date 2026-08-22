# M3 Teacher Usability and Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task. Every behavior change follows test-driven development and receives scoped commits per repository.

**Goal:** Enforce live teacher authorization and make prep, assessment preview, class context, insights, and resources usable without touching the user's dirty Butler/layout work.

**Architecture:** Keep FastAPI/Vue/Pinia and existing Artifact state machines. Add authorization once at the teacher router boundary, strengthen deterministic local content contracts, and render existing structured data at the page boundary.

**Spec:** `docs/superpowers/specs/2026-08-22-m3-teacher-usability-design.md`

## Global constraints

- Preserve all original uncommitted work and do not modify dirty Butler/layout/router-aggregation/global-style files.
- Work sequentially where files overlap; never reset or overwrite user changes.
- AI/local generation creates drafts only; PPT generation requires an independently confirmed lesson.
- No incomplete choice question may be published.
- Every task records RED/GREEN evidence, gets independent review, and does not merge or push.

### Task 1: Enforce verified teacher binding at the M3 boundary

**Backend files:** `app/domains/teacher/scope.py`, `app/domains/teacher/router.py`, `tests/_m3_helpers.py`, `tests/test_m3_teacher_scope.py`.

- [ ] Add failing tests for missing, unverified and soft-deleted teacher bindings, plus revocation after token issuance; retain active-role rejection.
- [ ] Make normal teacher helpers seed a verified `RoleBinding`.
- [ ] Add an async router dependency that first validates active role, then queries one non-deleted verified teacher binding for the token subject.
- [ ] Attach the dependency to the `/api/teacher` router so no endpoint can omit it. Keep service-level `require_teacher_role` calls for defense in depth.
- [ ] Verify teacher scope tests and all `test_m3_teacher*.py`; Ruff and diff-check.
- [ ] Commit backend: `fix(m3): require verified teacher binding`.

### Task 2: Make lesson preparation topic-driven and Artifact-faithful

**Backend files:** `app/domains/teacher/capability_gateway.py`, `tests/test_m3_teacher_lessons.py` (and the narrow lesson service file only if needed).

**Frontend files:** `src/pages/teacher/TeacherPrepView.vue`, relevant prep component test (new), optionally `src/types/teacher.ts` for a real contract field.

- [ ] RED backend: adapt “导数的概念” and assert exact topic, nonempty objectives, each timeline item has activities, no “不知道”/`Exit Ticket`; confirmed lesson download remains nonzero.
- [ ] RED frontend: enter topic/requirements/duration, assert exact request; Artifact activities are rendered; draft PPT action does not call confirm/slides and tells teacher to confirm.
- [ ] Implement a deterministic editable lesson draft keyed by topic and duration, with Chinese “当堂检测” and meaningful activity prompts.
- [ ] Add explicit topic, duration and class-needs inputs; blank topic is locally blocked. Apply real Artifact content, status and errors.
- [ ] Remove implicit confirmation from PPT generation. Confirm and generate remain separate explicit actions; confirmed slides download is preserved.
- [ ] Verify lesson tests, focused frontend test, full Vitest/typecheck/build, diff-check.
- [ ] Commit backend and frontend separately.

### Task 3: Validate and preview complete quiz questions

**Backend files:** `app/domains/teacher/assessment.py`, `tests/test_m3_teacher_assessment.py`.

**Frontend files:** `src/pages/teacher/TeacherAssignView.vue`, `src/types/teacher.ts`, focused preview component test.

- [ ] RED backend: a matching choice missing options or answer is excluded and triggers shortage; an analysis-missing but otherwise complete row remains and carries an explicit teacher warning.
- [ ] RED frontend: real object options, answer and `analysis` are visible; blank/text show no fake option list.
- [ ] Normalize/validate bank rows without relaxing KP/type; compute available count only from publishable items.
- [ ] Extend preview mapping/rendering for object/array options, standard answer and analysis/fallback text without global CSS changes.
- [ ] Verify assessment tests, mapping/publish-gate tests, focused preview test, full frontend checks.
- [ ] Commit backend and frontend separately.

### Task 4: Humanize Today/class context and expose safe invite/member data

**Backend files:** `app/domains/teacher/insights.py`, `app/domains/classroom/router.py`, related teacher-insight/classroom tests.

**Frontend files:** `src/pages/teacher/TeacherTodayView.vue`, `src/pages/teacher/TeacherClassesView.vue`, focused component/pure tests. Do not edit `src/api/index.js`.

- [ ] RED: insight evidence contains no internal `key=value`; members return user nickname with class nickname precedence; invite code appears only on teacher-owned class response.
- [ ] RED frontend: greetings normalize `李老师`/`李`/missing; seed member names and invite code display.
- [ ] Implement deterministic evidence templates per insight kind, preserving counts/time window.
- [ ] Join `User.nickname` for members and expose existing invite code only through authorized teacher list.
- [ ] Render normalized greeting, member names and invite code using page-local markup/styles only.
- [ ] Verify insight/classroom tests and full frontend checks.
- [ ] Commit backend and frontend separately.

### Task 5: Reject empty resources and preserve summary visibility

**Backend files:** `app/domains/teacher/resources.py`, `tests/test_m3_teacher_resources.py`.

**Frontend files:** `src/pages/teacher/TeacherResourcesView.vue`, focused resource component test.

- [ ] RED backend: 0B upload returns 400/422 with code 40001/message resource_empty and creates no File/Task/storage object.
- [ ] RED frontend: 0B File is blocked before API; a successful understand response immediately renders summary on the same card.
- [ ] Add the post-read/pre-write empty-content guard and page-local file-size precheck.
- [ ] Preserve nonempty upload, download, cross-teacher scope and summary behavior.
- [ ] Verify resource tests and full frontend checks.
- [ ] Commit backend and frontend separately.

### Task 6: Final verification, review and scoped integration

- [ ] Run all `test_m3_teacher*.py`, affected classroom tests, Ruff, and backend diff-check twice from a clean test DB reset.
- [ ] Run full Vitest, typecheck, build and isolated-port teacher E2E.
- [ ] Independent most-capable review checks security, mathematical/content correctness, contract compatibility and dirty-worktree conflicts.
- [ ] Cherry-pick only reviewed scoped commits into original branches after exact clean-path checks; stop on any conflict and never push.
