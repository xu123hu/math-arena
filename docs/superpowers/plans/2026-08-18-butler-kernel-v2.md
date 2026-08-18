# Butler Kernel v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏 M2 已有接口和数学领域服务的前提下，用类型化、可审计、可配置、可降级的 Butler Kernel v2 替换当前管家调度器，并补齐星辰/云配置及前端控制面。

**Architecture:** 现有 FastAPI Router 作为兼容壳，内部接入 Context → Plan → Policy → Execute → Compose 管线。PydanticAI 只负责结构化计划和输出校验；现有模型路由、领域服务、数据库、Redis 与星辰适配器继续作为基础设施。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、锁定版本的 PydanticAI 2.x、SQLAlchemy async、Alembic、Redis、pytest、Vue 3、Vite。

**Spec:** `docs/superpowers/specs/2026-08-18-butler-kernel-v2-design.md`

## Global Constraints

- 后端目录 `D:\math-arena\services\api`，前端目录 `D:\frontend`。
- 不得重置、覆盖或提交当前脏工作区中的既有修改。
- 保持 `/api/butler/*`、`/api/student/*`、`/api/agent/*` 兼容。
- LLM 不得直接写数学判定、掌握度、错题复习或成绩事实。
- M2 不实现或挂载 F14 `wf_verify_derivation`。
- 不使用 LangGraph、Pydantic Graph、Harness、多智能体、A2A 或代码沙箱。
- 单次运行最多 3 次模型请求、5 次工具调用；交互总超时 20 秒。
- 每个任务执行失败测试 → 最小实现 → 通过测试 → 独立提交。
- 真实 API key、AppId、Secret、Token 不得进入代码、测试、日志、文档或提交。

## File Map

**Backend create:**

- `app/butler/contracts.py`：核心类型。
- `app/butler/model_adapter.py`：PydanticAI 到现有 ModelRouter 的隔离层。
- `app/butler/context.py`：上下文快照。
- `app/butler/policy.py`：权限和预算校验。
- `app/butler/registry.py`：类型化工具注册。
- `app/butler/executor.py`：受限、幂等执行。
- `app/butler/composer.py`：规则数据优先的响应组合。
- `app/butler/runtime.py`：统一入口。
- `app/butler/workflow_tools.py`：星辰工具包装。
- `app/models/agent_run.py` 与 Alembic 迁移：运行账本。
- `tests/test_butler_{contracts,policy,registry,runtime,workflow_tools,compat}.py`。

**Backend modify:**

- `pyproject.toml`、`requirements.txt`。
- `app/butler/{orchestrator,tools,skills}.py`。
- `app/gateway/{butler_router,admin_router,integration_router,search_router}.py`。
- `app/main.py`、`app/models/{__init__,database}.py`。

**Frontend create/modify:**

- 新建 `src/pages/admin/*`、`src/components/admin/{SecretField,HealthBadge}.vue`、`src/components/chat/WebSearchToggle.vue`。
- 修改 `src/router/index.js`、`src/config/nav.js`、`src/api/index.js`、`ChatInput.vue`、`DialogView.vue`、`MessageBubble.vue`、`PracticeView.vue`。

---

### Task 1: 锁定基线、凭证和 M2 契约

**Files:** Create `tests/test_butler_compat.py`, `tests/test_m2_route_profile.py`.

**Produces:** 现有信封契约；M2 OpenAPI 不包含 F14 的可执行断言。

- [ ] 写失败测试：

```python
@pytest.mark.asyncio
async def test_dashboard_keeps_legacy_envelope(client, student_headers):
    r = await client.get("/api/butler/dashboard", headers=student_headers)
    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert r.json()["message"] == "ok"
    assert isinstance(r.json()["data"], dict)

def test_m2_openapi_excludes_f14(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/research/derivations/verify" not in paths
```

- [ ] 运行 `pytest tests/test_butler_compat.py tests/test_m2_route_profile.py -q`，确认 F14 测试失败。
- [ ] 只记录泄漏凭证的文件和字段名，由负责人在平台侧轮换；用 `<ROTATED_SECRET>` 清理文档，禁止在终端/回复复述值。
- [ ] 通过 feature profile 排除 M2 `research_router`，不要删除未来科研代码。
- [ ] 重跑聚焦测试并提交：`test: lock M2 butler boundaries`。

### Task 2: 修复练习契约与今日计划性能 P0

**Files:** Modify `app/gateway/student_router.py`, `app/butler/skills.py`, `D:\frontend\src\pages\student\PracticeView.vue`; test `test_student_pipeline.py`, `test_iter15_today_actions.py`.

**Produces:** 5 道唯一且可渲染题；整页最多一次 LLM 润色。

- [ ] 写失败测试：

```python
@pytest.mark.asyncio
async def test_practice_returns_five_unique_renderable_items(client, student_headers):
    r = await client.post("/api/student/practice/start", headers=student_headers, json={"count": 5})
    items = r.json()["data"]["items"]
    assert len(items) == 5
    assert len({x["id"] for x in items}) == 5
    assert all(x["interaction_type"] in {"choice", "blank", "text"} for x in items)

@pytest.mark.asyncio
async def test_daily_plan_calls_llm_at_most_once(monkeypatch, db, student_user):
    calls = 0
    async def fake(**kwargs):
        nonlocal calls
        calls += 1
        return kwargs["fallback"]
    monkeypatch.setattr("app.butler.llm.generate", fake)
    await daily_plan(db, student_user.id)
    assert calls <= 1
```

- [ ] 运行聚焦测试确认失败。
- [ ] 后端规范化 `interaction_type`，使用稳定 ID/hash 去重；前端只按规范字段渲染。
- [ ] 一次构建规则卡片，最多一次生成整页摘要，不逐卡润色。
- [ ] 运行聚焦测试、`pytest -q`、前端 `npm run build`；后端独立提交 `fix: stabilize M2 practice and plan contracts`。

### Task 3: 建立核心类型契约

**Files:** Create `app/butler/contracts.py`, `tests/test_butler_contracts.py`.

**Produces:** `ActorRole`, `ActorContext`, `ButlerRequest`, `ButlerContextSnapshot`, `PlannedAction`, `ActionPlan`, `ToolRisk`, `ToolResult`, `ButlerEnvelope`.

- [ ] 写 Action 超限、空 request id、extra field、非法 response mode 的失败测试。
- [ ] 运行测试确认 import/validation 失败。
- [ ] 按设计规格实现；Planner-facing 模型使用 `ConfigDict(extra="forbid")`，名称/ID 使用 `min_length=1`。
- [ ] 运行 `pytest tests/test_butler_contracts.py -q` 和 `mypy app/butler/contracts.py`。
- [ ] 提交 `feat: define Butler Kernel v2 contracts`。

### Task 4: 类型化 Registry 与 PolicyGate

**Files:** Create `app/butler/registry.py`, `app/butler/policy.py`, corresponding tests.

**Produces:** `ToolDefinition`, `ToolRegistry.register/visible_to`, `PolicyGate.validate_plan`.

- [ ] 写重复工具、未知工具、角色越权、场景越权、非法参数、预算超限和 F14 缺席测试：

```python
def test_student_cannot_plan_research_tool(policy, student_request):
    decision = policy.validate_plan(student_request, plan_for("research.verify_derivation"))
    assert decision.allowed is False
    assert decision.error_code in {"role_denied", "m2_out_of_scope", "unknown_tool"}

def test_m2_registry_has_no_f14(registry):
    assert "research.verify_derivation" not in registry.names()
```

- [ ] 运行测试确认失败。
- [ ] 用显式 allowlist 实现 Registry/Policy；稳定错误码为 `unknown_tool`, `role_denied`, `scene_denied`, `invalid_arguments`, `budget_exceeded`, `confirmation_required`, `m2_out_of_scope`。
- [ ] 运行聚焦测试并提交 `feat: add typed butler tool policy`。

### Task 5: PydanticAI 隔离适配

**Files:** Create `app/butler/model_adapter.py`; modify dependency files; extend `test_butler_runtime.py`.

**Consumes:** 当前 `ModelRouter.chat(...)`。

**Produces:** `ButlerModelAdapter`, `build_planner(adapter)`。

- [ ] 在可丢弃环境查看可用版本，选择一个具体 PydanticAI 2.x 补丁版本；两个依赖文件均使用相同 `==x.y.z`，不得使用无上限 `>=`。
- [ ] 写合法计划、无效 JSON、校验失败、一次修复、主备模型全失败的测试。
- [ ] Adapter 只接收已解析的 ModelRouter，不创建供应商或云网关，不持有密钥。
- [ ] 不依赖原生 Function Calling；解析结构化计划并交给 Pydantic 校验，失败后规则降级。
- [ ] 运行 `pytest tests/test_butler_runtime.py -q`、`python -m pip check` 并提交 `feat: isolate PydanticAI planner`。

### Task 6: Context、Executor 与运行账本

**Files:** Create `context.py`, `executor.py`, `models/agent_run.py`, Alembic migration; modify model registration; extend runtime tests.

**Produces:** `ContextAssembler.build`, `ButlerExecutor.execute`, `AgentRun`, `AgentStep`, `ToolInvocation`.

- [ ] 写上下文只读取一次、第五个后拒绝、写操作幂等、外部超时、失败不重放成功写的测试：

```python
@pytest.mark.asyncio
async def test_duplicate_write_returns_recorded_result(executor, write_tool):
    a = await executor.invoke(write_tool, args(), client_request_id="same")
    b = await executor.invoke(write_tool, args(), client_request_id="same")
    assert b.data == a.data
    assert write_tool.call_count == 1
```

- [ ] 新表索引：`agent_runs(user_id, created_at)`、唯一 `client_request_id`、`agent_steps(run_id, sequence)`、`tool_invocations(run_id, tool_name)`。
- [ ] 独立读取用 `asyncio.gather`，同一事务写操作不得并行。
- [ ] 账本只存脱敏摘要，不存密钥、完整隐私文本或思维链。
- [ ] 执行 `alembic upgrade head` → `downgrade -1` → `upgrade head`，运行测试并提交 `feat: add auditable idempotent butler execution`。

### Task 7: 包装现有领域工具

**Files:** Modify `app/butler/tools.py`, `registry.py`; extend registry/student linkage tests.

**Produces:** 设计规格中的 9 个本地工具。

- [ ] 参数化测试每个工具的名称、角色、输入和输出；断言 Registry 不包含判分/掌握度直接写工具。
- [ ] 包装现有函数，不重写 growth、question_supply、FSRS、图谱或任务服务。
- [ ] wrapper 调用前后分别校验输入和输出，异常转换为 `ToolResult`。
- [ ] 运行 registry 和 student linkage 测试并提交 `feat: expose M2 domains as typed butler tools`。

### Task 8: Runtime、Composer 与兼容壳

**Files:** Create `composer.py`, `runtime.py`; modify `orchestrator.py`, `butler_router.py`; extend runtime/compat tests.

**Produces:** `ButlerRuntime.run(request, db) -> ButlerEnvelope`。

- [ ] 写成功、模型失败降级、Policy 拒绝、工具超时、重复请求、Legacy 信封转换和 Shadow 无副作用测试。
- [ ] 实现 Context → Plan → Policy → Execute → Compose；每阶段记录 `AgentStep`。
- [ ] Composer 最多一次可选 LLM 调用且永远有规则回退。
- [ ] 增加 `BUTLER_V2_ENABLED`, `BUTLER_V2_SHADOW`, `M2_ENABLE_RESEARCH`；Shadow 把 WRITE/EXTERNAL 变为 `shadow_skipped`。
- [ ] 运行所有 Butler 测试和 `pytest -q`；提交 `feat: route M2 butler through Kernel v2`。

### Task 9: 星辰工具与联网搜索

**Files:** Create `workflow_tools.py`; modify `providers/xingchen.py`, `gateway/search_router.py`; create workflow tool tests.

**Produces:** 7 个允许的星辰工具和规范搜索来源。

- [ ] 写 allowlist、F14 缺席、Schema、超时、限流、无效 JSON、缺少 flow id、降级测试。
- [ ] 写搜索触发测试：

```python
def test_web_search_needs_opt_in_or_local_refusal(policy):
    assert not policy.allow_web_search(enabled_by_user=False, local_refused=False)
    assert policy.allow_web_search(enabled_by_user=False, local_refused=True)
```

- [ ] 包装现有 `run_workflow/stream_workflow`；来源统一为 `title/url/snippet/retrieved_at`。
- [ ] 搜索结果不得进入确定性判分；星辰故障返回明确降级而非 500。
- [ ] 运行 workflow/Xingchen 测试并提交 `feat: expose Xingchen as guarded butler tools`。

### Task 10: 配置即用后端控制面

**Files:** Modify `admin_router.py`, `integration_router.py`; extend admin/model/cloud-kb/embedding/Xingchen tests.

**Produces:** 有效来源、脱敏密钥、健康和连接测试。

- [ ] 参数化测试 env only、system > env、teacher/research user > system、student inherit、blank secret preserves old value。
- [ ] 对每个 admin GET/test 响应断言原始 secret 不存在。
- [ ] 每字段返回 `value/source/masked/editable`；健康返回 `status/latency_ms/checked_at/error_code/message`。
- [ ] 复用现有接口，只补缺失星辰 probe、有效来源和错误规范。
- [ ] 运行配置测试和 `pytest -q`，提交 `feat: complete configuration-first control plane`。

### Task 11: 管理前端与搜索体验

**Files:** Frontend files in File Map.

**Produces:** 可用 `/admin/*` 页面、角色守卫、搜索开关、来源与降级显示。

- [ ] 如果有测试框架则写路由/组件测试，否则写最小 Playwright smoke：管理员导航、密钥脱敏、保存/测试、学生搜索开关、来源、失败降级。
- [ ] 未登录去 `/login`；非管理员去 `/overview`；不能只检查 token。
- [ ] 页面只能调用 `src/api/index.js`，禁止散落 fetch；空 secret 表示保留旧值。
- [ ] 搜索默认关闭，失败保留本地答案并显示非阻塞降级。
- [ ] 运行 `npm run build` 和前端/Playwright 测试。
- [ ] 若 `D:\frontend` 不是 Git 仓库，不得 `git init`；报告精确改动文件并由负责人决定版本管理。

### Task 12: 完整验证、影子与切换

**Files:** Create `scripts/verify_butler_v2.py`, `docs/butler-kernel-v2-verification.md`; only modify defects proven by verification.

**Produces:** 带证据的 go/no-go 与回滚说明。

- [ ] 运行 `pytest -q`, `ruff check app tests`, `mypy app/butler`, `alembic current`；记录命令、退出码和摘要。
- [ ] 对 dashboard、daily-plan、recommend、error-tutor 各做足量采样，总计至少 30 次；记录 P50/P95、模型请求数、工具数、降级率。
- [ ] 分别注入主模型、备用模型、Redis、星辰、云 KB、Embedding 故障，核心学生流不得无解释 500。
- [ ] 运行安全/范围检查：

```powershell
rg -n "verify_derivation|wf_verify_derivation" services/api/app D:\frontend\src
git diff --check
git grep -n -I -E "(api[_-]?key|secret|token).{0,20}['\"][A-Za-z0-9_-]{16,}"
```

- [ ] 完成至少 10 条学生 E2E 和从空配置到启用的管理端 E2E。
- [ ] 先 `BUTLER_V2_SHADOW=true` 只读对比；达标后仅对金丝雀账户启用 v2；本发布不删除旧内核和回滚开关。
- [ ] 验证报告逐项 PASS/FAIL；任一门槛失败即 no-go，不得宣称完成。
- [ ] 提交 `test: verify Butler Kernel v2 release gates`。

## Self-Review Record

- 规格覆盖：内核、模型隔离、Policy、幂等、记忆复用、星辰边界、F14 排除、配置 UI、搜索、迁移和发布门槛均有任务。
- Placeholder 扫描：无 TBD/TODO/“稍后实现”；Alembic revision 与 PydanticAI 补丁版本由所属步骤通过真实环境生成/选择。
- 类型一致性：核心名称与设计规格一致。
- 子系统拆分：Task 3–8 是可独立验收内核，Task 9–10 是集成/控制面，Task 11 是独立构建前端，Task 12 是发布门。
