# Butler Kernel v2 阶段 6 实施计划：web_search_opt_in 安全传输链

> 状态：已按评审结论修订（v2），待批准
> 日期：2026-08-20
> 前置：阶段 5.1a 已 PASS（提交 `4d5492e`）
> 硬约束：本阶段不切流 v2、不改旧内核行为、不修改数据库模型/Alembic

## 1. 目标与边界

将 `web_search_opt_in` 从**真实 HTTP 请求**与**前端交互**安全地传输到 `ButlerRequest`，
为 v2 切流铺好管道。**本阶段只完成安全传输链，不宣称联网搜索已在旧 chat 内核生效。**

- 完成：HTTP schema 字段、Facade 映射、可信场景、Registry 场景、前端功能标志控制、传输链测试。
- 不做：v2 切流、旧 chat 内核接入联网搜索、来源/降级卡片渲染、在线 `run_v2_chat`。

## 2. 现状梳理（已核实）

| 层 | 现状 | 缺口 |
|---|---|---|
| 契约 | `ButlerRequest.web_search_opt_in: bool = False`（contracts.py） | 无 |
| 执行 | `ButlerExecutor.invoke` 已构造 `WebSearchAuthorization(global_enabled, user_opt_in=request.web_search_opt_in)` | 无 |
| Handler | `_h_web_search` fail-closed（auth=None / global off → 远程 0） | 无 |
| HTTP | `POST /chat`（agent_router.py）`ChatContext` 含 `thinking/skills/tutor_action/speech_inject`，无 `extra="forbid"`（默认 ignore） | **无 `web_search_opt_in` 字段** |
| 场景 | chat 流程当前无 Butler scene 概念；前端 `context.scene` 被 Pydantic 忽略 | **无可信场景 `student.chat`** |
| Registry | `xingchen.web_search` allowed_scenes = `{student.dashboard, student.practice, student.review, student.errors}` | **不含 `student.chat`** |
| v2 调用点 | 仅 dashboard 走 `run_v2_shadow`；chat 无 v2 钩子 | 本阶段**不建立**（D1/D3=否） |
| 前端 | `D:\frontend`：`useChat.js` 构造 `payload.context`；`ChatInput.vue` 有 thinking 开关模式 | **无联网开关、无功能标志门控** |
| 版本管理 | `D:\frontend` 非 Git 仓库 | **开工前需解决**（硬要求 5） |

## 3. 后端改动（services/api）

### 3.1 HTTP Schema 增加字段（仅此一项）

`app/gateway/agent_router.py` → `ChatContext` 增加：

```python
# 联网搜索请求级授权（默认关；单条请求授权，不持久化）
web_search_opt_in: bool = False
```

- **只增加该字段，不改动 `ChatContext` 的 extra 字段策略**（保持现状，不引入 `extra="forbid"`）。
- 纯增量；旧前端不传 → 默认 False（fail-closed）。

### 3.2 可信场景 student.chat（后端定义，不接受客户端决定）

- 后端定义常量可信场景 `student.chat`（如 `app/butler/scenes.py` 或 contracts 常量）。
- Facade 构造 `ButlerRequest` 时，scene **由后端从已认证用户与 workspace 推导**，绝不读取客户端传入的 scene。
- 客户端 `context.scene`（当前被 Pydantic 忽略）保持忽略，不接入 Butler 场景判定。

### 3.3 Compatibility Facade（HTTP → ButlerRequest）

新增 `app/butler/facade.py`，提供唯一映射函数：

```python
def build_butler_request_from_chat(
    *,
    user_id: uuid.UUID,
    role: ActorRole,
    message: str,
    scene: str,  # 后端推导的可信场景，如 student.chat
    conversation_id: uuid.UUID | None,
    client_request_id: str,
    web_search_opt_in: bool = False,
) -> ButlerRequest:
    ...
```

- 单一事实源：HTTP/领域入口构造 `ButlerRequest` 必须经此函数。
- `web_search_opt_in` 直接透传（默认 False）。
- **本阶段不新增在线 `run_v2_chat`**；字段进入 `ButlerRequest` 由 Facade 集成测试证明（D3=否）。

### 3.4 Registry allowed_scenes 增加 student.chat

- `xingchen.web_search` 的 `allowed_scenes` 增加 `student.chat`。
- 必要只读工具（chat 场景所需）同步增加 `student.chat`（范围见决策点 D4）。
- 新增 Policy 测试：`student.chat` 场景下 `xingchen.web_search` 可见/可规划；非学生角色仍拒绝。

## 4. 前端改动（D:\frontend）

### 4.1 开工前置：版本管理（硬要求 5）

- 开工前确认 `D:\frontend` 版本管理方案（负责人决定：纳入主仓库 / 独立 Git / 其他）。
- **禁止触碰主仓库旧 `apps/web` 删除项**（保持未暂存状态，不纳入任何提交）。

### 4.2 联网开关：功能标志门控 + 默认隐藏（硬要求 3）

- v2 未切流期间，联网按钮**必须受功能标志控制且默认隐藏**，禁止公开无效按钮。
- 功能标志来源：后端 `/api/agent/features`（或既有 features 接口）返回 `web_search_opt_in_enabled: false`（v2 未切流期间恒为 false）。
- 前端仅当标志为 true 时才渲染按钮；当前恒隐藏。

### 4.3 开关语义：单条请求授权，发送后自动复位（D2=不持久化）

- 开关默认关闭；用户开启 → 本次发送携带 `web_search_opt_in: true` → **发送后自动复位为关**。
- 不写入 localStorage、不持久化偏好。
- `useChat.js`：`payload.context` 增加 `...(webSearchOn ? { web_search_opt_in: true } : {})`。

### 4.4 范围裁剪（硬要求 4）

- **删除本阶段"来源/降级卡片"范围**。
- 等 v2 SSE 适配时复用既有 citation/badge 渲染，本阶段不新增渲染组件。

## 5. 测试方案

### 后端（RED→GREEN，TDD）

| 测试 | 断言 |
|---|---|
| `test_chat_context_accepts_web_search_opt_in` | `ChatContext(web_search_opt_in=True)` 可解析；缺省 False；extra 策略未变 |
| `test_facade_maps_web_search_opt_in` | Facade 传入 True → `ButlerRequest.web_search_opt_in is True`；缺省 → False |
| `test_facade_trusted_scene` | Facade 使用后端推导的 `student.chat`，忽略客户端 scene |
| `test_registry_web_search_allows_student_chat` | `xingchen.web_search` allowed_scenes 含 `student.chat` |
| `test_policy_student_chat_web_search_visible` | `student.chat` 场景下学生可见/可规划 web_search；教师/管理员仍拒绝 |
| `test_butler_request_optin_enters_context`（已有） | 经 `ButlerExecutor` 验证 `web_search_opt_in` 进入 `ToolExecutionContext` |

### 前端

- 最小 Playwright smoke（若 `D:\frontend` 有测试框架）：功能标志 false 时按钮不渲染；标志 true 时开关默认关、发送后复位、请求体携带 `web_search_opt_in: true`。

## 6. 验收标准

- [ ] 新增后端测试红→绿；全部 `test_butler*.py` 通过
- [ ] 阶段 5.1 的 admin/RAG/星辰配置测试通过
- [ ] `ruff`、`git diff --cached --check`、密钥扫描通过
- [ ] `D:\frontend` 构建通过；联网按钮默认隐藏（标志 false）；开关发送后自动复位
- [ ] 完整 `pytest -q` 一次通过
- [ ] 独立提交（后端与前端分别提交；前端版本管理按 D5 方案执行）
- [ ] v2 保持不切流（`_v2_migrated_scenes()` 仍为空；`BUTLER_V2_ENABLED` 默认 false）
- [ ] 回报明确声明：本阶段只完成安全传输链，联网搜索未在旧 chat 内核生效（硬要求 7）

## 7. 决策点（评审已定 + 待确认）

**已定（评审结论）：**
- D1=否：不建立 live chat v2 shadow 分支
- D2=不持久化：联网授权为单条请求授权，默认关闭，发送后自动复位
- D3=否：不新增在线 `run_v2_chat`；用 Facade 集成测试证明字段进入 ButlerRequest

**待确认：**
- D4：`student.chat` 加入哪些"必要只读工具"的 allowed_scenes？
  - 推荐：仅 `xingchen.web_search`（本阶段聚焦联网授权，最小范围）。
  - 备选：web_search + 学生只读领域工具（如 `student.profile.read` 等，需列清单）。
- D5：`D:\frontend` 版本管理方案（硬要求 5 前置，开工前必须确定）。

## 8. 明确不做

- 不切流 v2（`_v2_migrated_scenes()` 保持为空；`BUTLER_V2_ENABLED`/`BUTLER_V2_SHADOW` 默认值不变）
- 不修改旧内核 chat 行为；不宣称联网搜索在旧 chat 内核生效
- 不新增在线 `run_v2_chat` / chat v2 shadow 分支
- 不实现"来源/降级卡片"渲染（等 v2 SSE 适配复用既有 citation/badge）
- 不修改数据库模型 / Alembic；不改动 `ChatContext` 的 extra 字段策略
- 不触碰主仓库旧 `apps/web` 删除项
- 不实现 F14 / lean / 多智能体
