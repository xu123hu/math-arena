# 学生错题本配图与正解持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复错题本原题配图，并将需图题目的正解和示意图首次生成后持久化。

**Architecture:** 后端用一个资源规范化服务将历史图片、帧数据和 GeoGebra 构造转换成统一契约；错题记录保存正解和正解图。正解接口在行锁内先读取缓存，只有缓存为空才生成并保存。前端只渲染规范化资源，原题图与正解图独立展示。

**Tech Stack:** FastAPI、SQLAlchemy async、Alembic、PostgreSQL JSONB、Vue 3、Vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-09-01-student-error-book-assets-design.md`

## Global Constraints

- 不批量调用模型回填历史数据；仅首次访问且正解缓存为空时生成。
- 输出资源只能是 `{type:'image',src,alt}` 或合法 GeoGebra `ggb` 对象。
- 只有原题已有图或题干含明确图形依赖时才生成正解图；图形失败不得影响正解保存。
- 缓存命中时不得调用 `butler_llm.generate`；并发请求同一错题最多生成一次。
- 保持 `record.user_id == current_user` 授权校验；不得把当前未提交的改动加入本任务提交。

---

### Task 1: 统一错题图片资源

**Files:**
- Create: `services/api/app/services/error_record_assets.py`
- Modify: `services/api/app/gateway/student_router.py:90-170,659-710`
- Modify: `services/api/app/gateway/growth_router.py:976-1025`
- Test: `services/api/tests/test_error_record_assets.py`

**Interfaces:**
- `normalize_error_assets(items: list | None) -> list[dict]` 接受 URL/data URI 字符串、`src`/`url`/`data_uri` 对象、图形帧和现有 ggb，输出两种规范资源。
- `has_usable_figure(question_text: str, assets: list[dict]) -> bool` 仅对已有图或“如图、图中、几何、平面、棱、垂直、平行”等图形语义返回真。

- [ ] **Step 1: Write the failing test**
  - 断言 `{frames:[{data_uri:'data:image/svg+xml,abc'}]}` 规范为 `{type:'image',src:'data:image/svg+xml,abc',alt:'题目配图'}`。
  - 断言含命令的 ggb 被保留并补全空 caption，未知对象被丢弃。

- [ ] **Step 2: Run test to verify it fails**
  - Run: `pytest services/api/tests/test_error_record_assets.py -q`
  - Expected: FAIL，因为规范化服务不存在。

- [ ] **Step 3: Write minimal implementation**
  - 新建规范化服务；在 `_upsert_error_record`、`POST /error-records/{id}/figure` 写入前及 `error_record_detail` 输出前调用它。

- [ ] **Step 4: Run tests to verify it passes**
  - Run: `pytest services/api/tests/test_error_record_assets.py services/api/tests/test_error_dedup.py -q`
  - Expected: PASS。

- [ ] **Step 5: Commit**
  - `git add services/api/app/services/error_record_assets.py services/api/app/gateway/student_router.py services/api/app/gateway/growth_router.py services/api/tests/test_error_record_assets.py`
  - `git commit -m "fix(student): normalize error book image assets"`

### Task 2: 正解与正解图持久化

**Files:**
- Create: `services/api/alembic/versions/om7_error_record_solution_cache.py`
- Modify: `services/api/app/models/coursework.py:221-258`
- Modify: `services/api/app/butler/skills.py:254-306`
- Test: `services/api/tests/test_error_solution_cache.py`

**Interfaces:**
- 增加 `ErrorRecord.generated_answer: str | None`、`solution_figure: list` 与 `solution_generated_at`。
- `error_detail(db, user_id, record_id)` 返回 `generated_answer`、`solution_figure`、`cached: bool`。

- [ ] **Step 1: Write the failing test**
  - 给记录预置 `generated_answer='已保存的正解'`，将 `butler_llm.generate` 替换为会抛错的 mock；断言接口返回缓存且 `cached is True`。
  - 让模型返回“新正解”、正解图生成抛错；断言文本被保存且 `solution_figure == []`。

- [ ] **Step 2: Run test to verify it fails**
  - Run: `pytest services/api/tests/test_error_solution_cache.py -q`
  - Expected: FAIL，因为缓存列和响应字段不存在。

- [ ] **Step 3: Write minimal implementation**
  - 迁移新增 `generated_answer TEXT NULL`、`solution_figure JSONB NOT NULL DEFAULT '[]'`、`solution_generated_at TIMESTAMPTZ NULL`。
  - 在 `error_detail` 用 `select(ErrorRecord).with_for_update()` 读取并授权；若有文本直接返回。否则只生成一次，图形仅在 `has_usable_figure` 为真时 best-effort 生成，规范化后将文本、图和时间在同一事务提交。

- [ ] **Step 4: Run tests to verify it passes**
  - Run: `pytest services/api/tests/test_error_solution_cache.py services/api/tests/test_iter05_student.py -q`
  - Expected: PASS。

- [ ] **Step 5: Commit**
  - `git add services/api/alembic/versions/om7_error_record_solution_cache.py services/api/app/models/coursework.py services/api/app/butler/skills.py services/api/tests/test_error_solution_cache.py`
  - `git commit -m "fix(student): persist error book solutions"`

### Task 3: 学生端安全展示

**Files:**
- Modify: `D:/frontend/src/components/DynamicFigureViewer.vue:1-70`
- Modify: `D:/frontend/src/pages/student/ErrorsView.vue:131-145,326-361,489-520`
- Test: `D:/frontend/test/student/errorBookAssets.test.ts`

**Interfaces:**
- 查看器仅接受规范 `image` 和 `ggb`；图片加载失败显示“配图暂不可用”，不留下破损图标。
- `ErrorsView` 将 `detailFull.solution_figure || []` 放在正解文本上方的独立查看器中。

- [ ] **Step 1: Write the failing test**
  - 传入 `{type:'image',src:'data:image/svg+xml,abc',alt:'题目配图'}` 后断言 img 的 src 正确。
  - 模拟缓存正解响应，断言出现“正解示意图”且不出现“AI 生成中”。

- [ ] **Step 2: Run test to verify it fails**
  - Run: `pnpm vitest run test/student/errorBookAssets.test.ts`
  - Expected: FAIL，因为对象图片与正解图尚未渲染。

- [ ] **Step 3: Write minimal implementation**
  - `DynamicFigureViewer` 的静态图 computed 改为读取 `{type:'image',src,alt}`，模板使用 src/alt 并在 error 后移除该资源和显示空态。
  - `ErrorsView` 增加 `solutionFigItems`；非空时渲染“正解示意图”。接口返回前才显示“正解加载中”，不以缓存命中为生成状态。

- [ ] **Step 4: Run tests to verify it passes**
  - Run: `pnpm vitest run test/student/errorBookAssets.test.ts test/student && pnpm build`
  - Expected: PASS，构建退出码为 0。

- [ ] **Step 5: Commit**
  - `git -C D:/frontend add src/components/DynamicFigureViewer.vue src/pages/student/ErrorsView.vue test/student/errorBookAssets.test.ts`
  - `git -C D:/frontend commit -m "fix(student): render persisted error-book figures"`

### Task 4: 并发与最终验收

**Files:**
- Modify: `services/api/tests/test_error_solution_cache.py`

- [ ] **Step 1: Write the failing test**
  - 使用 `asyncio.gather` 并发请求同一个 `/api/butler/error-detail/{id}`；mock 模型返回“唯一正解”，断言两个响应相同且模型 await 次数为 1。

- [ ] **Step 2: Run test to verify it fails**
  - Run: `pytest services/api/tests/test_error_solution_cache.py::test_two_simultaneous_detail_requests_generate_once -q`
  - Expected: 在未加行锁时 FAIL。

- [ ] **Step 3: Write minimal implementation**
  - 保持 Task 2 的行锁读取—缓存检查—生成—提交顺序，不增加客户端缓存或第二层缓存。

- [ ] **Step 4: Run final evidence suite**
  - Run: `pytest services/api/tests/test_error_record_assets.py services/api/tests/test_error_solution_cache.py services/api/tests/test_error_dedup.py -q && pnpm -C D:/frontend vitest run test/student/errorBookAssets.test.ts && pnpm -C D:/frontend build && git diff --check`
  - Expected: 全部退出码为 0。

- [ ] **Step 5: Commit**
  - `git add services/api/tests/test_error_solution_cache.py`
  - `git commit -m "test(student): cover error solution cache concurrency"`

