# M3 Teacher Core Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make teacher assessment and grading class-scoped, knowledge-point faithful, and reviewable with full question context.

**Architecture:** Keep the current FastAPI/Vue/Pinia architecture. Add authorization at query boundaries, remove cross-topic fallback generation, derive grading context from persisted QuizItem records, and expose the contract to the teacher UI.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, PostgreSQL, pytest; Vue 3, Pinia, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-22-m3-teacher-core-integrity-design.md`

## Global Constraints

- Preserve every pre-existing uncommitted user change.
- Do not modify dirty Butler/layout/router/global-style files in this batch.
- AI suggestions never write formal scores without teacher confirmation.
- Never widen knowledge points to fill a quiz silently.
- Each behavior change follows red-green-refactor and gets a scoped commit.

---

### Task 1: Enforce class scope on list endpoints

**Files:**
- Modify: `services/api/app/domains/teacher/assessment.py`
- Modify: `services/api/app/domains/teacher/grading.py`
- Test: `services/api/tests/test_m3_teacher_scope.py`

**Interfaces:**
- Consumes: `assert_teacher_in_class(db, teacher_id, class_id)`.
- Produces: `list_assignments(...)` and `grading_queue(...)` reject unauthorized explicit class IDs with code 40302.

- [ ] **Step 1: Write failing API tests**

```python
@pytest.mark.asyncio
async def test_teacher_cannot_list_another_class_assignments(client):
    owner, foreign_class = await seed_foreign_class()
    response = await client.get(
        f"/api/teacher/assignments?class_id={foreign_class}",
        headers=_auth(token(await seed_teacher(), "teacher")),
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40302
```

Add the equivalent grading queue case with a populated foreign submission so an empty response cannot satisfy the test.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_m3_teacher_scope.py -q`

Expected: both explicit foreign-class list tests fail because current endpoints return 200.

- [ ] **Step 3: Implement the boundary check**

```python
if class_id is not None:
    await assert_teacher_in_class(db, teacher_id, class_id)
    class_ids = [class_id]
else:
    class_ids = await teacher_class_ids(db, teacher_id)
```

- [ ] **Step 4: Verify GREEN and regressions**

Run: `python -m pytest tests/test_m3_teacher_scope.py tests/test_m3_teacher_assessment.py tests/test_m3_teacher_grading.py -q`

- [ ] **Step 5: Commit**

```bash
git add services/api/app/domains/teacher/assessment.py services/api/app/domains/teacher/grading.py services/api/tests/test_m3_teacher_scope.py
git commit -m "fix(m3): enforce teacher class scope on list queries"
```

### Task 2: Make quiz generation knowledge-point faithful

**Files:**
- Modify: `services/api/app/domains/teacher/assessment.py`
- Modify: `services/api/tests/test_m3_teacher_assessment.py`
- Create: `src/domain/teacher/quizConfig.ts` in the frontend worktree
- Modify: `src/pages/teacher/TeacherAssignView.vue` in the frontend worktree
- Test: `test/teacher/quizConfig.test.ts` in the frontend worktree

**Interfaces:**
- Produces: `resolveScopeKnowledgePoints(scope): string[]`.
- Produces: quiz Artifact fields `content.insufficient`, `validation.requested_count`, `validation.available_count`.

- [ ] **Step 1: Write failing backend tests**

Use a unique KP code per test and delete the inserted `QuestionBank` rows in fixture teardown. Assert that requesting five questions from a one-row bank returns exactly the one matching question, `degraded=true`, `content.insufficient=true`, and no `local_template` item.

- [ ] **Step 2: Verify backend RED**

Run: `python -m pytest tests/test_m3_teacher_assessment.py -q`

Expected: current cross-topic fallback produces five items and violates the no-template assertion.

- [ ] **Step 3: Implement strict shortage behavior**

Remove `_local_fallback_item`; keep only strict bank rows. Store requested/available counts, mark insufficient, and emit a teacher-facing warning. Do not invent an answer or analysis.

- [ ] **Step 4: Write and verify failing frontend mapping tests**

```typescript
expect(resolveScopeKnowledgePoints('monotonicity')).toEqual(['MATH-003'])
expect(resolveScopeKnowledgePoints('derivative')).toEqual(['MATH-004'])
expect(() => resolveScopeKnowledgePoints('unknown')).toThrow('未知知识点范围')
```

Run: `npm test -- --run test/teacher/quizConfig.test.ts`

Expected: FAIL because the mapping module does not exist.

- [ ] **Step 5: Implement mapping and publish gate**

Import `resolveScopeKnowledgePoints`, send its result in `generatePaper`, and disable publication while `quizArtifact.content.insufficient === true`.

- [ ] **Step 6: Verify GREEN**

Run backend: `python -m pytest tests/test_m3_teacher_assessment.py -q`

Run frontend: `npm test -- --run test/teacher/quizConfig.test.ts test/teacher/stores.test.ts`

- [ ] **Step 7: Commit per repository**

```bash
git commit -am "fix(m3): prevent cross-topic quiz fallback"
git commit -m "fix(m3): map teacher quiz scope to real knowledge points"
```

### Task 3: Add grading question context and correct objective scoring

**Files:**
- Modify: `services/api/app/domains/teacher/grading.py`
- Modify: `services/api/tests/test_m3_teacher_grading.py`
- Modify: `src/types/teacher.ts` in the frontend worktree
- Modify: `src/pages/teacher/TeacherGradingView.vue` in the frontend worktree

**Interfaces:**
- Produces `GradingDetail.question_text`, `question_type`, `options`, `standard_answer`, `answer_analysis`, `assignment_title`.

- [ ] **Step 1: Write failing backend tests**

Create a real Quiz/QuizItem/Assignment/Submission chain. Assert a wrong choice returns 0 with high confidence, a correct case-insensitive choice returns 1, missing standard answer requires review, and detail includes literal question/option/title fields.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_m3_teacher_grading.py -q`

Expected: wrong non-empty choice currently receives 1 and detail fields are absent.

- [ ] **Step 3: Implement minimal scoring/context lookup**

Add one helper that loads `QuizItem` by `(sub.quiz_id, item.item_no)`. Compare normalized scalar answers only for choice/judge. Reuse the helper in suggestion and detail serialization.

- [ ] **Step 4: Extend frontend contract and display**

Add the six optional fields to `GradingDetail`. Render assignment title and question before the original answer; render options as a list and label the standard answer/analysis as teacher-only reference.

- [ ] **Step 5: Verify GREEN and build**

Run backend: `python -m pytest tests/test_m3_teacher_grading.py tests/test_m3_teacher_e2e.py tests/test_m3_fullstack_closure.py -q`

Run frontend: `npm test -- --run && npm run build`

- [ ] **Step 6: Commit per repository**

```bash
git commit -am "fix(m3): grade objective items against persisted answers"
git commit -am "feat(m3): show full question context during grading"
```

### Task 4: Final review and integration

**Files:**
- Review both worktree diffs and commits.

- [ ] **Step 1: Run complete scoped verification**

Backend: all `test_m3_teacher*.py`, `test_m3_fullstack_closure.py`, and `git diff --check`.

Frontend: Vitest, teacher-scoped typecheck evidence, Vite build, and updated teacher E2E smoke where selectors are current.

- [ ] **Step 2: Independent code review**

Reviewer checks security scope, mathematical correctness, API compatibility, dirty-worktree collision risk, and regression evidence.

- [ ] **Step 3: Integrate only scoped commits**

Cherry-pick backend commits into `feat/backend-m1` and frontend commits into `master`. Stop on any conflict; never overwrite user changes.

