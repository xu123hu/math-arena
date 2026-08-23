# Butler Kernel v2 · 阶段 2 交付报告（Contracts / Registry / PolicyGate）

- **日期**：2026-08-18
- **基线**：HEAD `4afce83`（干净 Git 归档：routes=26 / collect=817 / Alembic 单头 m2_017）
- **结论**：PASS（仅 mypy 工具环境不可用，见 §8）
- **下一阶段准入**：YES

## 1. 修改文件（精确清单）

| 文件 | 类型 | 说明 |
|------|------|------|
| `services/api/app/butler/contracts.py` | 新增 | 核心类型契约（10 个类型） |
| `services/api/tests/test_butler_contracts.py` | 新增 | 22 个测试 |
| `services/api/app/butler/registry.py` | 新增 | 类型化工具注册表 + M2 拒绝名单 |
| `services/api/tests/test_butler_registry.py` | 新增 | 17 个测试 |
| `services/api/app/butler/policy.py` | 新增 | PolicyGate 10 步校验 + 9 稳定错误码 |
| `services/api/tests/test_butler_policy.py` | 新增 | 22 个测试 |

未触碰任何禁止文件（orchestrator / skills / tools / butler_router / student_router / ModelRouter / Xingchen / DB 模型 / Alembic / requirements / pyproject / D:\frontend）。

## 2. 类型与公开接口清单（contracts.py）

| 类型 | 字段 / 值 | 关键约束 |
|------|-----------|---------|
| `ActorRole` (StrEnum) | student / teacher / researcher / admin | — |
| `ActorContext` | user_id: UUID, role: ActorRole, class_ids: tuple[UUID,...]=(), locale="zh-CN" | extra="forbid" |
| `ButlerRequest` | actor, message, scene, conversation_id?, source_event_id?, client_request_id | scene/client_request_id `min_length=1`；extra="forbid" |
| `ButlerContextSnapshot` | actor, scene, profile: dict[str,Any], conversation: dict[str,Any], assignments: tuple[dict,...], effective_config: dict[str,Any], feature_flags: frozenset[str] | 类型化模型非裸 dict；extra="forbid" |
| `PlannedAction` | tool_name, arguments: dict[str,Any]={}, reason | tool_name `min_length=1`；extra="forbid" |
| `ActionPlan` | intent, goal, actions: list[PlannedAction] (max 5), response_mode: Literal[direct/cards/socratic/degraded], needs_web_search=False | extra="forbid" |
| `ToolRisk` (StrEnum) | read / learning_action / write / external / role_restricted | — |
| `ToolResult` | ok, data=None, error_code?, user_message?, retryable=False, degraded=False | extra="forbid" |
| `ButlerEnvelope` | run_id, intent, text, blocks=[], actions=[], sources=[], degraded=False, trace={} | extra="forbid" |
| `ButlerBudget` | max_model_requests=3, max_tool_calls=5, timeout_s=20.0 | extra="forbid" |

## 3. Registry（registry.py）公开接口

- `M2_DENIED_TOOLS`：`{research.verify_derivation, wf_verify_derivation, lean.verify, lean.prove, lean.check}`
- 异常：`ToolRegistryError` ← `DuplicateToolError` / `UnknownToolError` / `ToolForbiddenError`
- `ToolDefinition`：name(min_length=1)/version/description/input_model/output_model/risk/allowed_roles/allowed_scenes/timeout_s=20.0/idempotency_required=False/handler
- `ToolRegistry.register/get/names/visible_to/validate_arguments/validate_output`
- 无 eval/getattr 反射；handler 由后续 Executor 显式调用
- 注册层直接拒绝 M2 名单名（`ToolForbiddenError`）

## 4. PolicyGate（policy.py）公开接口

- `PolicyDecision`：allowed / error_code / message / blocked_tool（extra="forbid"）
- `PolicyGate.validate_plan(request, plan, *, budget, web_search_enabled, web_search_local_refused, external_allowed)`
- `PolicyGate.validate_action(request, action, *, external_allowed)`
- `PolicyGate.allow_web_search(*, enabled_by_user, local_refused) -> bool`

### 固定 10 步校验顺序与错误码

| 步 | 检查 | 稳定错误码 |
|----|------|-----------|
| 1 | 工具是否注册 | `unknown_tool` |
| 2 | 角色是否允许 | `role_denied` |
| 3 | 场景是否允许 | `scene_denied` |
| 4 | 参数是否合法 | `invalid_arguments` |
| 5 | 工具数量 ≤ budget.max_tool_calls | `budget_exceeded` |
| 6 | 风险等级 ∈ allowed_risks（默认全枚举） | `risk_denied` |
| 7 | WRITE 必须 idempotency_required | `idempotency_required` |
| 8 | EXTERNAL 需 external_allowed | `external_not_allowed` |
| 9 | 搜索需显式开启或本地拒答 | `confirmation_required` |
| 10 | M2 范围排除（m2_denied_tools 兜底） | `m2_out_of_scope` |

错误响应固定文案，不含堆栈 / 内部类名 / 数据库信息 / 密钥（ValidationError 详情被吞掉，仅返回 `invalid tool arguments`）。

## 5. F14 护栏（双保险）

1. **注册层**：`ToolRegistry.register` 命中 `M2_DENIED_TOOLS` → `ToolForbiddenError`（参数化测试覆盖 4 个 F14 名）。
2. **调用层**：即使绕过注册层（宽松 registry 注入），`PolicyGate` 第 10 步返回 `m2_out_of_scope`。
3. 未注册的 F14 名 → 第 1 步 `unknown_tool` 拒绝。
4. 学生规划 teacher/research/admin 工具 → 参数化测试断言 `role_denied`。

## 6. TDD 红→绿证据

| 步骤 | 命令 | 结果 |
|------|------|------|
| 红 | `pytest tests/test_butler_contracts.py -q` | collection error（模块不存在） |
| 绿 | 同上 | **22 passed** |
| 红 | `pytest tests/test_butler_registry.py -q` | collection error（模块不存在） |
| 绿 | 同上 | **17 passed** |
| 红 | `pytest tests/test_butler_policy.py -q` | collection error（模块不存在）→ 实现后 5 个失败（测试参数缺省触发 invalid_arguments 前置拦截，修正测试输入聚焦意图） |
| 绿 | 同上 | **22 passed** |
| 聚焦 | 三文件合并 | **61 passed** |

15 项验收测试全部覆盖：6 Action 拒绝（contracts max_length=5 + budget 检查）、空 client_request_id、extra 字段、重复工具、未知工具、学生调教师工具、场景不匹配、参数类型错误、WRITE 无幂等、EXTERNAL 未授权、搜索显式开启、本地拒答、均无时禁止、F14 注册/调用拒绝、错误信息不泄漏内部异常。

## 7. 静态检查与全量回归

| 检查 | 命令 | 结果 |
|------|------|------|
| ruff | `ruff check app/butler/contracts.py app/butler/registry.py app/butler/policy.py tests/test_butler_*.py` | **All checks passed**（9 个 UP035/F401/F541 已修） |
| mypy | `mypy app/butler/contracts.py app/butler/registry.py app/butler/policy.py` | ⚠️ 环境不可用（见 §8） |
| py_compile | 6 个文件 | OK |
| 完整 pytest | `pytest -q` | **871 passed, 7 skipped, 0 failed**（878 collected；基线 817 无回归，新增 61 全过） |
| git diff --check | 两次提交前 | 无错误 |

## 8. mypy 环境问题（如实上报）

- venv 内 mypy **2.3.0（mypyc 编译版）** 在本沙箱对**任何文件**（最小探针 `x: int = 1`）都静默退出 1：无输出、无 traceback、faulthandler 无效；`mypy --version` 正常。
- pip 走 `127.0.0.1:7897` 代理连接被拒（沙箱无外网），无法降级安装稳定版 mypy。
- 一次罕见成功运行中，本次 3 个新文件 **0 错误**（150 个错误全部来自 app/ 既有文件，strict 模式历史欠账，与本阶段无关）。
- 结论：非本阶段代码问题。阶段 3 需在正常终端执行 mypy，或在可写缓存环境重跑 `mypy --python-version 3.12`。

## 9. 提交

| 提交 | 消息 |
|------|------|
| `2f656b6` | feat: define Butler Kernel v2 contracts |
| `7695d3a` | feat: add typed butler registry and policy |

提交链：`4afce83` → `2f656b6` → `7695d3a`（HEAD）。

## 10. 范围确认

- ✅ 未引入 PydanticAI（`pydantic_ai` 未安装；仅 pydantic 2.13.4）
- ✅ 未注册真实领域工具（仅测试工具）
- ✅ 禁止文件零触碰；前端零改动
- ✅ 阶段 2 准入：**YES**（等待阶段 3 放行：PydanticAI 隔离适配 Task 5–8）

---

# 附：阶段 2.1 Policy 边界加固（提交 `9811188`）

主体复核通过后，按"只修 3 个已证明漏洞"加固 Policy 边界，单提交 `fix: close Butler policy authorization bypasses`，仅改 6 个允许文件（3 源 + 3 测试）。

## A. 修复 lean.* 前缀绕过

- **漏洞**：`M2_DENIED_TOOLS` 只列 lean.verify/lean.prove/lean.check，`lean.custom` 可注册。
- **修复**：`registry.py` 新增统一函数（单一逻辑源）：

```python
def is_m2_denied_tool(name: str) -> bool:
    return name in M2_DENIED_TOOLS or name.startswith("lean.")
```

- `ToolRegistry.register` 与 `PolicyGate` 第 10 步共同调用；第 10 步保留 `self._m2_denied_tools` 自定义名单 OR 组合。
- **语义变化**：register 永久拒绝 M2/lean 名（不再能通过 denied_tools 放宽）；Policy 兜底测试改为直接塞入 `reg._tools[name]` 模拟"绕过注册层"。
- 测试：`lean.custom` / `lean.any_future_tool` 注册拒绝；塞入 `lean.custom` 后 Policy 仍返回 `m2_out_of_scope`；非 Lean 工具（含 `xingchen.web_search`）注册不受影响。

## B. 修复联网搜索授权绕过

- **漏洞**：只检查 `plan.needs_web_search`；计划直接含 `xingchen.web_search` 且 `needs_web_search=false` + `external_allowed=true` 时放行。
- **修复**：`policy.py` 新增 `WEB_SEARCH_TOOLS={"xingchen.web_search"}` + `is_web_search_tool(name)`（显式名单 + `.web_search` 后缀）；**以实际 Action 工具名为最终依据**：

```python
def is_web_search_tool(name: str) -> bool:
    return name in WEB_SEARCH_TOOLS or name.endswith(".web_search")
```

- `validate_action` 增加 `web_search_enabled: bool = False` / `web_search_local_refused: bool = False`（默认安全拒绝）；`validate_plan` 向每个 Action 传递真实状态。
- 校验顺序保持：EXTERNAL 未授权 → `external_not_allowed`（先）；EXTERNAL 已授权但搜索未确认 → `confirmation_required`。
- 测试：needs_web_search=false 但 Action 是搜索工具仍拒；validate_action 单独调用默认拒、enabled_by_user=true 放行、local_refused=true 放行、两者均 false 拒；任意 `*.web_search` 后缀工具被检查。

## C. 修复无效预算

- **修复**：`ButlerBudget` 边界 `max_model_requests: ge=1, le=3`；`max_tool_calls: ge=1, le=5`；`timeout_s: gt=0, le=20.0`。允许降低、不允许超限/零/负。
- 测试：0/负数/4 模型/6 工具/超 20 → ValidationError；1/1/0.1 合法；默认 3/5/20 不变。

## 验证证据

| 项 | 结果 |
|----|------|
| 红（修复前） | **20 failed / 67 passed**——三类绕过全部复现 |
| 绿（修复后） | **87 passed**（61 原有 + 26 新增） |
| ruff 6 文件 | All checks passed |
| git diff --check | 无错误 |
| mypy | 2.3.0 INTERNAL ERROR（既有工具链债务，不阻塞；本次 3 文件无错误行） |
| 完整 pytest | 按用户指示未跑（模块未接入 Runtime，聚焦通过即进入阶段 3） |

## 提交与范围

- `9811188 fix: close Butler policy authorization bypasses`（6 files changed, +300/-25）
- 提交链：`4afce83` → `2f656b6` → `7695d3a` → `9811188`
- 仅修改 6 个允许文件；未触碰 PydanticAI/Runtime/Executor/数据库/星辰/前端
- 阶段 3 准入：**YES**
