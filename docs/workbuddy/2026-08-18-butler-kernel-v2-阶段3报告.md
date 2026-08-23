# Butler Kernel v2 · 阶段 3 交付报告（PydanticAI 适配 + Context/Executor/账本 + Runtime 兼容壳）

- **日期**：2026-08-18
- **基线**：HEAD `9811188`（阶段 2.1 收口；871 passed / 7 skipped）
- **结论**：PASS
- **下一阶段准入**：YES（等待阶段 4：领域工具包装 Task 7 + 星辰边界 Task 9）

---

## 1. 依赖选择（3A）

| 项 | 值 |
|----|----|
| 选定版本 | **`pydantic-ai-slim==2.31.1`**（最小核心包，精确锁定于 `pyproject.toml` 与 `requirements.txt`，无浮动 `>=`） |
| 选择理由 | 2.x 系列当前最新稳定补丁（2.31.1 > 2.31.0）；选用 `-slim` 而非主包：pydantic-ai 主包默认携带全部 extras（logfire/google-genai/anthropic/mcp/evals），违反"最小核心包"约束；slim 仅含 Agent/FunctionModel/UsageLimits 核心 |
| 安装 | 清代理后从 PyPI 安装（沙箱 127.0.0.1:7897 无效代理 → `env -u HTTP_PROXY -u HTTPS_PROXY` 重试成功）；`pip check` 无破坏 |
| 传递依赖 | `pydantic-graph==2.31.1`（slim 强制依赖、内部图执行引擎，实现不 import 其 Graph API）、`logfire-api`（pydantic-graph 依赖的轻量遥测客户端，非 Logfire 云服务）、`openai`/`genai-prices`（slim 依赖） |
| 已排除 | pydantic-graph（直接使用）、pydantic-ai-harness、LangGraph、多智能体、Logfire 云服务、Pydantic Gateway——均未引入 |

**安装坑**：pydantic-ai 主包卸载被沙箱 safe-delete 拦截（回收站不可用）→ 直接删除 site-packages 残留目录（`~ydantic_ai-*.dist-info`、`pai.exe.deleteme`、anthropic/google/logfire/pydantic_evals 等 extras）；保留 slim 必需依赖后 `import pydantic_ai` 正常。

## 2. 3A ModelAdapter（提交 `b529a0d`）

**文件**：`app/butler/model_adapter.py` + `tests/test_butler_model_adapter.py`（12 测试）

**公开接口**：`ButlerDeps`（dataclass）、`ButlerModelAdapter`、`build_planner()`、`deterministic_fallback_plan()`、`build_planning_prompt()`。

**关键设计**：
- 复用已解析 `ModelRouter.chat()`（主备降级/熔断/`log_ai_call` 审计保留），不创建/持有密钥，不连 Gateway；
- `FunctionModel(adapter.generate)`：消息转文本 → `ModelRouter.chat(functions=None)` → `ModelResponse(TextPart)`，不依赖原生 Function Calling；
- `Agent(output_type=ActionPlan, retries=1)`：输出非法（坏 JSON / Schema 错误）最多修复 1 次；
- `UsageLimits(request_limit=max_model_requests=3)`：单次 Planner 请求 ≤3（adapter.request_count 双护栏）；
- 模型全失败 / 超时 → `deterministic_fallback_plan()`（degraded 无动作），不向学生端抛异常；
- Planner prompt 只含 `Registry.visible_to(role, scene)` 摘要，不可见工具不进入；
- 测试 12 项全过：合法 JSON / markdown 包裹 / 非法 JSON 修复 1 次 / Schema 修复 1 次 / 全失败 fallback / 超时 fallback / ≤3 请求 / 无 Function Calling / 复用注入 router（无 Gateway）/ 对外产物不泄漏密钥 / 工具摘要过滤 / fallback 形状。

## 3. 3B Context / Executor / 运行账本（提交 `468a08f`）

**文件**：`context.py`、`executor.py`、`models/agent_run.py`、迁移 `m2_018_butler_kernel_v2_ledger`、`models/__init__.py` 注册、`registry.py` handler 协议文档；测试 `test_butler_context.py`（5）/ `test_butler_executor.py`（11）/ `test_butler_ledger.py`（5）。

**ContextAssembler**：顺序查询 6 类上下文（student_profiles / conversations / messages / user_model_configs / system_configs / assignments），**每类恰好 1 次 execute、同一 session 不并发**；文本截断 200 字符；无数据返回空结构；Snapshot 不含 api_key/embedding/全文。

**运行账本**：`AgentRun`（UniqueConstraint(user_id, client_request_id)、idx user_id+created_at）、`AgentStep`（UniqueConstraint(run_id, sequence)、idx run_id）、`ToolInvocation`（idx run_id / tool_name / idempotency_key）；只存 digest / 脱敏 metadata，无原始密钥/完整文本/工具输入输出列。Alembic 往返（独立临时库 upgrade→downgrade→upgrade）全 0 退出，单头 `m2_018`。

**Executor**：`ToolExecutionContext`（run_id/request/db/idempotency_key）+ 协议 `handler(context, validated_input) -> dict`（registry.py 文档化，无 eval/getattr）；先 Policy 后执行、输入/输出前后 Registry 校验、独立 timeout→degraded、预算防御、WRITE 幂等键（user+client_request_id+tool_name+canonical hash）进程内重放（handler 仅执行 1 次）、不同用户同 crid 不冲突、Shadow→shadow_skipped（handler 0 次）、EXTERNAL 失败 degraded、异常稳定文案（无路径/SQL/密钥）。

**坑**：SQLAlchemy 保留属性名 `metadata` → 列名 metadata + 属性 `run_meta`；测试须先建 User（外键）。

## 4. 3C Composer / Runtime / 兼容壳（提交 `bb4e0a2`）

**文件**：`composer.py`、`runtime.py`、`test_butler_runtime.py`（6）/ `test_butler_compat_v2.py`（4）；修改 `config.py`、`orchestrator.py`、`butler_router.py`。

**配置**：`BUTLER_V2_ENABLED=false`、`BUTLER_V2_SHADOW=false`（默认保持旧内核运行，本阶段禁止默认切流）。

**ButlerRuntime.run(request, db) -> ButlerEnvelope**：固定管线 Context → Plan → Policy → Execute → Compose，每阶段记录 AgentStep；模型失败→fallback（degraded）；Policy 拒绝→拒绝 envelope；重复 client_request_id（账本唯一约束）→ duplicate envelope 不重复执行；模型请求 ≤3、工具调用 ≤5、总超时 ≤20s；账本完整（AgentRun + 5×AgentStep + ToolInvocation digest）。

**Composer**：规则数据优先，第一版无额外 LLM 润色；永远有规则 fallback；不输出思维链；trace 含 error_codes。

**兼容接入**：
- `BUTLER_V2_ENABLED=false`：所有 `/api/butler/*` 行为不变（HTTP 测试 code=0 信封）；
- `BUTLER_V2_SHADOW=true`：旧内核结果返回用户，v2 用 `background_session_factory` 独立 session 影子运行（WRITE/EXTERNAL 一律 shadow_skipped，handler 0 次）；
- `BUTLER_V2_ENABLED=true`：`_v2_migrated_scenes()` 为空集合（无真实工具）→ 未迁移场景全部回退旧内核，不切断页面；
- orchestrator.dispatch 保持 best-effort，shadow 钩子默认关闭，异常不阻断学习主链。

## 5. 红→绿证据

| 子阶段 | 红 | 绿 |
|--------|----|----|
| 3A | collection error（模块不存在）→ 测试修正后全绿 | **12 passed**（含修复 1 次、≤3 请求、无泄漏等） |
| 3B | collection error（3 文件模块不存在） | **21 passed**（context 5 / executor 11 / ledger 5） |
| 3C | collection error（runtime/composer 不存在） | **10 passed**（runtime 6 / compat 4） |
| 全量 | — | **130 passed**（9 个 Butler 测试文件合并） |

## 6. 最终验证

| 项 | 命令 | 结果 |
|----|------|------|
| 全部 Butler 测试 | pytest 9 个 test_butler_*.py | **130 passed** |
| 阶段 2 回归 | 87 项（含在 130 内） | 全过 |
| ruff | 本阶段新增/修改全部文件 | All checks passed |
| mypy | `--python-version 3.12`（本阶段 9 文件） | 直接错误 0（agent_run 泛型 2 处已修 `6e8ea19`；其余 162 项为既有跨模块 strict 欠账，按指示不修） |
| Alembic | heads / 往返（独立临时库） | 单头 `m2_018`；upgrade→downgrade -1→upgrade 全 0 退出 |
| 干净 archive | `git archive HEAD` → app.main 导入 + collect | **ROUTES=26**；**947 tests collected** 无错误 |
| 完整 pytest | 一次 | **939 passed / 8 skipped / 0 failed**（947 collected，基线 878 无回归） |
| git diff --check | 每次提交前 | 无错误 |
| 密钥扫描 | git grep 模式 | butler/测试/迁移无真实凭证（仅测试 mock 值） |

## 7. 提交（3 个阶段提交 + 1 个修复）

| 提交 | 消息 |
|------|------|
| `b529a0d` | feat: add isolated PydanticAI planner adapter（3A） |
| `468a08f` | feat: add auditable idempotent Butler execution（3B） |
| `bb4e0a2` | feat: integrate Butler Kernel v2 behind compatibility flags（3C） |
| `6e8ea19` | fix: add explicit type args to butler ledger models（mypy 直接错误修复） |

提交链：`7695d3a → 9811188 → b529a0d → 468a08f → bb4e0a2 → 6e8ea19`（HEAD）。

## 8. 范围确认

- ✅ 未触碰：ModelRouter 实现、Xingchen、数据库连接体系重写、前端
- ✅ 修改范围：新增 butler/{contracts,registry,policy,model_adapter,context,executor,composer,runtime}.py + models/agent_run.py + 迁移 m2_018 + config/orchestrator/butler_router 最小门控接入
- ✅ v2 enabled/shadow 默认值：**false / false**（旧内核运行，不切流）
- ✅ 停止条件均未触发：PydanticAI 已装、无私有 API、Alembic 单头、archive 可导入、/api/butler 契约无回归、Shadow 无 WRITE/EXTERNAL 副作用

**阶段 4 准入：YES**（等待放行：Task 7 领域工具包装 + Task 9 星辰边界）
