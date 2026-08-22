# M3 Teacher Fullstack Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox tracking and must be completed in order.

**Goal**

Deliver an engineering-grade teacher experience where lesson preparation, PPT export, quiz creation, assignment publication, student text/photo submission, teacher grading, student feedback, resources, classroom mode, and learning insights form one truthful local-first teaching loop. External AI workflows may be unavailable, but every workflow must have a deterministic local fallback.

**Architecture**

Keep FastAPI and PostgreSQL as the source of truth. Extend the existing M3 teacher domain instead of introducing parallel APIs. Persist classroom state, bind every submission to an authorized published assignment and quiz, expose confirmed grading to students, and generate office artifacts locally. Keep the existing Vue layouts while removing production-path mock fallbacks and wiring buttons to existing/new APIs.

**Tech Stack**

Python 3.11+, FastAPI, SQLAlchemy async, Alembic, PostgreSQL, pytest, Vue 3, Pinia, Vite, Vitest, browser automation. PPTX generation uses a locally packaged implementation and must not depend on an external AI service.

**Spec**

`docs/superpowers/specs/2026-08-22-m3-fullstack-closure-design.md`

## Global Constraints

- Preserve unrelated dirty-worktree changes in `D:\math-arena` and `D:\frontend`.
- Work in the existing directories because the user explicitly approved full-stack modification there.
- Never present mock rows or invented counts when an API succeeds with an empty result.
- All external AI failures must return a useful deterministic local artifact with explicit degraded metadata.
- Teacher-only mutations require teacher scope; student submission requires assignment visibility and membership.
- Each task follows red test, minimal implementation, green test, then a narrowly scoped commit when safe.

---

## Task 1: Repair database compatibility and persist classroom mode

- [ ] Add a failing migration/model test in `services/api/tests/test_m3_fullstack_closure.py` asserting `daily_questions.user_id` and `classroom_modes` exist after upgrade.
- [ ] Run `pytest services/api/tests/test_m3_fullstack_closure.py -k "schema or classroom" -q` and capture the failure.
- [ ] Add `services/api/alembic/versions/m3_002_fullstack_closure.py`: add/backfill `daily_questions.user_id`, replace the global date uniqueness with `(user_id, date)`, and create `classroom_modes` with class primary key, teacher, lesson, enabled, expiry, timestamps.
- [ ] Add `ClassroomMode` to `services/api/app/models/teacher.py` and import it from `services/api/app/models/__init__.py`.
- [ ] Replace `_CLASSROOM_STATE` in `services/api/app/domains/teacher/classroom.py` with database upsert/read and expiry handling while preserving the response contract and audit write.
- [ ] Run the targeted schema/classroom tests and `services/api/tests/test_m3_teacher_classroom.py` until green.

## Task 2: Enforce and prove the assignment-to-grading teaching loop

- [ ] Extend `services/api/tests/test_m3_fullstack_closure.py` with separate real teacher and student users: publish a confirmed quiz, verify visibility, submit text plus uploaded image/file reference, verify grading queue, suggest/override/confirm, and verify student result.
- [ ] Run the new closure test and record the first failing boundary.
- [ ] In `services/api/app/gateway/student_router.py`, validate assignment UUID, published/open status, class/target membership, quiz binding, item membership, and uploaded file ownership before creating a submission.
- [ ] Add/extend student assignment detail and result endpoints in `services/api/app/gateway/student_router.py` so confirmed scores and teacher feedback are visible only to the submitting student.
- [ ] In `services/api/app/domains/teacher/grading.py`, ensure confirmation is idempotent, updates the submission aggregate once, and only confirmed scores feed result/mastery data.
- [ ] Update Today/insights queries to use real submissions and remove invented count arithmetic.
- [ ] Run student pipeline/linkage, teacher assessment/grading/today/scope, and the new closure tests until green.

## Task 3: Provide deterministic local fallbacks and real downloadable PPTX

- [ ] Add failing tests for all seven capability workflows with no external workflow configured; assert successful degraded artifacts with usable content rather than unavailable status.
- [ ] Add a failing PPT export test asserting ZIP/PPTX signature, MIME type, non-empty slides, and downloadable file ownership.
- [ ] Implement local fallbacks in `services/api/app/domains/teacher/capability_gateway.py` for lesson draft, lesson adaptation, slide outline, quiz generation, grading suggestion, resource understanding, and class insight.
- [ ] Implement PPTX creation behind the lesson/slides endpoint using a repository-vendored minimal OOXML writer or an already-present approved dependency; save through the existing file domain and return `file_id`, name, MIME type, and degraded metadata.
- [ ] Ensure quiz fallback creates valid objective and subjective items with answers, analysis, knowledge point, difficulty, and stable schema.
- [ ] Run capability, lesson, assessment, resource, and PPT export tests until green.

## Task 4: Make resources a truthful usable workflow

- [ ] Add failing tests for upload, local text extraction, understanding fallback, publish/unpublish, list, and download authorization.
- [ ] Complete `services/api/app/domains/teacher/resources.py` and its router contracts so local extract/understand remains useful without AI.
- [ ] Ensure empty resource lists remain empty and failures expose explicit degraded reasons without synthetic resources.
- [ ] Run resource and file-domain tests until green.

## Task 5: Connect the Vue teacher and student experience to real data

- [ ] Add/update frontend tests asserting successful empty APIs render empty states and never append mock rows or invented counts.
- [ ] Remove real-mode mock fallback logic from `D:\frontend\src\pages\teacher\TeacherTodayView.vue`, `TeacherClassesView.vue`, `TeacherGradingView.vue`, and `TeacherResourcesView.vue`.
- [ ] Wire prepare, PPT export/download, quiz confirm, assignment publish, grading confirm, classroom toggle, resource upload/process/publish, and student assignment/upload/result actions through `D:\frontend\src\api\index.js`.
- [ ] Preserve existing layouts and provide loading, empty, degraded, success, and actionable error states for every operation.
- [ ] Run frontend unit tests and `npm run build` until green.

## Task 6: Perform final engineering verification

- [ ] Apply Alembic upgrade to the local database, restart backend and frontend, and reseed only the documented demo identities if needed.
- [ ] Run the focused M3 backend suite, migration/profile tests, frontend tests, and production build with fresh output.
- [ ] Use the real browser to log in as teacher and student and exercise every menu item, including file/PPT download and photo submission; verify network writes and post-refresh persistence.
- [ ] Restart the backend and verify classroom state plus published/student/grading data persist.
- [ ] Produce `docs/audits/2026-08-22-m3-teacher-engineering-audit.md` with requirement-to-test evidence, exact residual limitations, and no unsupported completion claims.

## Plan Self-Review

- The design spec's teaching loop, data truthfulness, persistence, seven fallbacks, resources, PPT, permissions, and browser verification are each mapped to a task.
- No task contains TODO/TBD placeholders; exact target files and required assertions are named.
- Backend IDs remain UUIDs and frontend transports them as strings; scores remain numeric at API boundaries; degraded status is explicit metadata rather than fabricated success data.
- The plan does not require external AI credentials or a remote workflow to close the teaching loop.
