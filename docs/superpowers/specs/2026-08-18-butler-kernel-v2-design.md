# Butler Kernel v2 设计规格

**状态：** 已批准（2026-08-18）

**范围：** M2 学生端 AI 管家底座，并为 M3 教师端、M4 科研端提供可复用内核

**代码目录：** `D:\math-arena`（后端），`D:\frontend`（测试前端）

## 1. 决策摘要

采用“兼容壳下替换内核”的渐进式重构：

- 保持现有 `/api/butler/*`、`/api/student/*`、`/api/agent/*` 北向契约兼容；
- 保留 FastAPI、SQLAlchemy、PostgreSQL、Redis、学习事件、数学判定、模型路由和星辰适配器；
- 使用锁定版本的 PydanticAI 2.x 实现类型化计划生成和输出校验；
- 不依赖模型原生 Function Calling，模型只生成结构化 `ActionPlan`；
- 由确定性 Policy 与 Executor 校验并执行工具；
- M2 不引入 LangGraph、Pydantic Graph、PydanticAI Harness、多智能体、A2A 或代码沙箱；
- 星辰是远程能力提供者，不是全局编排器；
- F14 `wf_verify_derivation` 不属于 M2，M2 运行配置不得挂载或展示。

## 2. 不可破坏的产品边界

M2 学生闭环保持不变：遇到题目 → 引导思考 → 独立作答 → 判分与错因 → 变式训练 → 错题复习 → 学情与行动更新。

LLM 不得直接决定或写入：数学答案正确性、表达式等价性、学生掌握度、错题复习状态、练习/考试/任务成绩、角色权限和配置优先级。这些事实只能由既有确定性领域服务产生。LLM 可以解释、建议、计划和润色，但不是事实源。

## 3. 总体架构

```text
Vue / existing API clients
            |
            v
Butler Compatibility Facade
            |
            v
ContextAssembler -> Planner -> PolicyGate -> Executor -> ResultComposer
        |            |           |           |             |
        |            |           |           |             +-> ButlerEnvelope/UI blocks
        |            |           |           +-> Typed Tool Registry
        |            |           +-> roles, permissions, budgets, preconditions
        |            +-> PydanticAI Agent[ButlerDeps, ActionPlan]
        +-> DB/Redis/profile/conversation/event snapshot

Typed Tool Registry
  +-- local read and learning-action tools
  +-- guarded write tools
  +-- Xingchen workflow tools
  +-- cloud KB / embedding tools

Shared infrastructure
  +-- current ModelRouter through ButlerModelAdapter
  +-- current memory/event system through MemoryBridge
  +-- AgentRun / AgentStep / ToolInvocation ledger
```

## 4. 核心契约

```python
class ActorRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    RESEARCHER = "researcher"
    ADMIN = "admin"

class ActorContext(BaseModel):
    user_id: UUID
    role: ActorRole
    class_ids: tuple[UUID, ...] = ()
    locale: str = "zh-CN"

class ButlerRequest(BaseModel):
    actor: ActorContext
    message: str
    scene: str
    conversation_id: UUID | None = None
    source_event_id: UUID | None = None
    client_request_id: str

class PlannedAction(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str

class ActionPlan(BaseModel):
    intent: str
    goal: str
    actions: list[PlannedAction] = Field(max_length=5)
    response_mode: Literal["direct", "cards", "socratic", "degraded"]
    needs_web_search: bool = False

class ToolRisk(StrEnum):
    READ = "read"
    LEARNING_ACTION = "learning_action"
    WRITE = "write"
    EXTERNAL = "external"
    ROLE_RESTRICTED = "role_restricted"

class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error_code: str | None = None
    user_message: str | None = None
    retryable: bool = False
    degraded: bool = False

class ButlerEnvelope(BaseModel):
    run_id: UUID
    intent: str
    text: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    trace: dict[str, Any] = Field(default_factory=dict)
```

每个工具必须声明唯一名称、版本、输入模型、输出模型、风险级别、角色集合、场景集合、默认超时、幂等策略和降级策略。Compatibility Facade 将 `ButlerEnvelope` 转换为已有 `{code: 0, message: "ok", data: ...}` 信封。

## 5. 运行管线

### ContextAssembler

一次并行读取并组装不可变快照：角色、对话摘要、学生画像、到期错题、薄弱点、任务、功能开关和有效配置。禁止在同一次运行中重复查询相同数据。

### Planner

- 使用 `Agent[ButlerDeps, ActionPlan]`；
- 通过 `ButlerModelAdapter` 调用当前 `ModelRouter`；
- 每次运行最多 3 次模型请求；
- 计划校验失败时最多修复 1 次；
- 模型全部失败时生成规则型降级计划；
- 不启用开放式自主循环。

### PolicyGate

依次校验：工具注册、角色、场景、参数模型、请求/工具/Token/时间预算、写工具幂等、联网搜索触发条件、M2 范围。失败转换为可审计拒绝或降级，不能静默越权。

### Executor

- 顺序执行有依赖动作，无依赖只读动作可并行；
- 默认工具上限 5；交互总超时 20 秒，后台工作流 60 秒；
- 写工具用 `client_request_id + tool_name + canonical_args` 生成幂等键；
- 外部失败不能造成成功写操作重复；
- 星辰失败时使用本地能力或清晰空态，并设置 `degraded=True`。

### ResultComposer

组合确定性数据、工具结果和最多一次文案生成。首页/计划类请求先返回规则数据，LLM 只做一次可缓存润色，禁止串行润色每张卡片。

## 6. 模型适配

新增 `ButlerModelAdapter`，实现 PydanticAI 所需接口，内部只调用现有 `ModelRouter.chat()`，保留星火主通道、DeepSeek 兜底、审计、熔断和用户有效配置。

适配器必须：

- 转换消息并从模型文本提取 JSON 后交给 Pydantic 校验；
- 归一化 `auth_error`、`rate_limit`、`timeout`、`unavailable`、`invalid_response`；
- 不把 API key 写入日志、异常或前端；
- 支持测试用确定性假模型；
- 允许未来替换 PydanticAI 而不改领域工具。

依赖使用锁定的、通过兼容测试的 PydanticAI 2.x 补丁版本，不使用浮动无上限依赖，也不接入 Pydantic 云网关。

## 7. 工具边界

首批本地工具：

- `student.profile.read`
- `student.errors.due.read`
- `student.mastery.weak_points.read`
- `knowledge.prerequisites.read`
- `practice.variants.create`
- `learning.path.recommend`
- `ui.route.build`
- `assignment.list`
- `review.plan.read`

星辰工具：

- `xingchen.document_understand`
- `xingchen.speech_to_latex`
- `xingchen.web_search`
- `xingchen.smart_quiz`
- `xingchen.solution_pregrade`
- `xingchen.error_analysis`
- `xingchen.course_preprocess`

`wf_socratic_chat` 不拥有多轮主状态；引导式解题由本地 Tutor/Butler 状态管理，星辰只作为可替换生成后端。`wf_verify_derivation` 不注册到 M2 Tool Registry，`research_router` 不在 M2 profile 挂载。

## 8. 记忆与运行账本

复用 Redis、`StudentProfile`、`EpisodicMemory`、`LearningEvent` 和对话记录，不启用框架自带第二套会话存储。

新增：

- `AgentRun`：入口、角色、场景、状态、预算、耗时、降级原因；
- `AgentStep`：context/plan/policy/execute/compose 阶段状态；
- `ToolInvocation`：工具版本、脱敏参数摘要、结果状态、耗时、幂等键。

账本不得保存密钥、完整隐私文本或模型隐藏思维链。

## 9. 配置控制面

配置优先级：`环境变量兜底 < 系统管理员默认 < 教师/科研用户覆盖`。学生继承有效配置且不可查看密钥。

管理端必须提供模型、星辰、工作流、云知识库、Embedding 页面；脱敏凭证编辑；有效值及来源；保存校验；独立连通测试；健康状态和失败原因；工作流启停、超时和 ID 配置。空白部署必须不改代码即可配置、测试和启用。

## 10. 前端行为

- 保持学生路由和 `butlerApi` 兼容；
- 增加 `/admin/*` 实际路由和页面；
- 对话输入区增加默认关闭的“联网搜索”开关；
- 本地知识库拒答时可提示切换联网搜索；
- 搜索回答展示来源、时间和降级状态，不参与数学判分；
- 学生界面只显示简洁进度，不展示内部思维链；
- 修复练习接口返回题型与前端可作答题型冲突，并去重题目。

## 11. 迁移策略

采用 Strangler + Shadow：锁定基线 → Facade 接入 → 只读场景切换 → 写/外部场景切换 → 无副作用影子运行 → 对比契约/延迟/工具选择 → 金丝雀启用 → 保留一个发布周期回滚开关 → 最后删除旧内核。

禁止一次性重写全部 Router、领域服务或前端 API。

## 12. 验收门槛

### 功能与安全

- 现有后端测试无回归，M2 学生 API 契约通过；
- 引导式解题 100 题盲测平均不低于 4/5，直接答案泄漏为 0；
- 数学判定仍走确定性服务；学生不能调用教师/科研/管理工具；
- F14 不在 M2 路由、工具和管理工作流列表；
- 密钥不出现在响应、日志、Git diff 或文档；已泄漏凭证完成轮换。

### 性能与可靠性

- dashboard/今日计划不串行发起多次文案模型调用；
- 规则数据首次可用 P95 小于 2 秒；需要模型的完整交互 P95 小于 8 秒；
- 单次运行模型请求不超过 3、工具调用不超过 5；
- 星辰、云 KB、Embedding 或主模型故障时核心学习功能可降级；
- 重复 `client_request_id` 不产生重复写操作。

### 配置即用与前端

- 新部署只通过管理界面完成模型、星辰、工作流、云 KB 和 Embedding 配置；
- 每种配置可测试并显示有效来源，学生看不到密钥；
- `D:\frontend` 构建通过，学生主流程至少 10 条 E2E 通过；
- 练习开始返回 5 道前端可作答且不重复的题；
- 联网搜索入口、来源展示和失败降级通过；
- 管理端配置页面可保存、回显、测试和显示脱敏值。

## 13. 明确不做

- M2 不实现 Lean、沙箱证明或 F14；
- 不建设多智能体网络；
- 不立即迁移全部本地数据到云，只完成适配接口和可配置切换；
- 不让 LLM 自主执行任意代码、SQL 或 HTTP；
- 不为框架统一而重写稳定领域服务；
- 不把星辰或其他工作流平台的私有状态作为唯一事实源。
