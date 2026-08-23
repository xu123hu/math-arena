# M3 Teacher Documentation Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 M3 教师端文档统一到获批的 v2.1 产品 SSOT，并给出可直接指导 M3 开发的 Butler Kernel v2、API、前端和星辰工作流派生契约。

**Architecture:** 保留 `M3_教师端详细需求分析_v2.1_AI管家高中教师版.md` 为唯一产品事实源；新增版本化派生文档，旧版 API/前端/技术/工作流文档仅保留归档提示。M3 后端采用现有 FastAPI + Butler Kernel v2 的教师 Profile/Registry 扩展，不引入第二套 Agent 编排框架。

**Tech Stack:** Markdown、HTML 原型、FastAPI、PydanticAI Butler Kernel v2、PostgreSQL、Vue 3、Pinia、星辰工作流、PptxGenJS、SymPy、KaTeX、MathLive、JSXGraph。

**Spec:** `D:/M2开发/M3教师端/M3_教师端详细需求分析_v2.1_AI管家高中教师版.md`

## Global Constraints

- 教师端只覆盖高中日常教学闭环，不注册建模教练、论文初审、评委评审、科研事实核验。
- 前端只认识 7 个业务能力：`adapt_lesson`、`create_slides`、`create_quiz`、`suggest_grade`、`explain_problem`、`preprocess_course`、`understand_document`。
- 教师端工作流名称统一为 `wf_lesson_plan`、`wf_ai_ppt`、`wf_explainer_script`、`wf_smart_quiz`、`wf_solution_pregrade`、`wf_course_preprocess`、`wf_doc_understand`。
- AI 产出必须先成为可编辑 Artifact，再经教师确认进入正式业务状态。
- 星辰不可用时必须走本地业务降级；不得让工作流故障阻断备课、出题、批改或课堂任务。
- 现有 `build_m2_registry()` 的 16 个工具均为 student-only；M3 必须新增 teacher-only 包装，禁止扩大原工具角色集合。
- `BUTLER_V2_ENABLED` 当前默认 `false`；教师场景按 shadow → 单场景切流推进。

---

### Task 1: 建立新版文档索引与归档边界

**Files:**
- Modify: `D:/M2开发/M3教师端/README.md`
- Modify: `D:/M2开发/M3教师端/教师端文档SSOT与科研边界迁移说明_v2.1.md`
- Modify: `D:/M2开发/M3教师端/M3_教师端详细需求分析_v2.1_AI管家高中教师版.md`

**Interfaces:**
- Consumes: 获批的分层 SSOT 方案。
- Produces: 唯一文档优先级、版本索引、派生文档命名和变更规则。

- [ ] **Step 1:** 重写 README，使产品 SSOT、API、前端、工作流、技术实现、原型的职责互斥。
- [ ] **Step 2:** 在迁移说明中加入新版派生契约、归档规则和 M0–M2 代码现实。
- [ ] **Step 3:** 在需求 SSOT 中加入“派生契约与实现基线”章节，不修改已确认功能范围。
- [ ] **Step 4:** 运行 `rg -n "唯一事实来源|产品 SSOT|归档" D:/M2开发/M3教师端/*.md`，确认没有第二份产品 SSOT。

### Task 2: 生成 Butler Kernel v2 教师端技术实现说明

**Files:**
- Create: `D:/M2开发/M3教师端/教师端AI管家_产品与技术实现说明_v2.2.md`
- Modify: `D:/M2开发/M3教师端/教师端AI管家_产品与技术实现说明_v2.1.md`

**Interfaces:**
- Consumes: 当前 `ActorRole`、`ToolRegistry`、`PolicyGate`、`ButlerRuntime`、16 个 M2 student-only 工具、配置控制面。
- Produces: Teacher Profile、Scene、Tool、Artifact、状态、切流和 M0–M2 复用契约。

- [ ] **Step 1:** 写明 7 工作区到 teacher scene 的精确映射。
- [ ] **Step 2:** 写明 teacher-only 工具、输入输出、风险级别、确认和 class scope。
- [ ] **Step 3:** 写明 Capability Gateway、领域服务、工作流适配器和本地降级的调用边界。
- [ ] **Step 4:** 写明 shadow → canary → enabled 的切流门禁和可观测指标。
- [ ] **Step 5:** 将 v2.1 文档标为归档并指向 v2.2。

### Task 3: 生成工作流指南 v1.3

**Files:**
- Create: `D:/M2开发/M3教师端/教师端工作流搭建指南_v1.3_高中教师版.md`
- Modify: `D:/M2开发/M3教师端/教师端工作流搭建指南_v1.2_高中教师版.md`

**Interfaces:**
- Consumes: 7 个标准工作流名称、现有 Xingchen Provider、管理配置接口。
- Produces: 精确输入输出 Schema、超时、错误映射、验证和本地替代规则。

- [ ] **Step 1:** 统一 `wf_ai_ppt` 和 `wf_explainer_script` 名称。
- [ ] **Step 2:** 规定工作流只做单次结构化生成，不拥有多轮状态和正式业务状态。
- [ ] **Step 3:** 为 7 个工作流给出输入、输出、超时、敏感数据和降级契约。
- [ ] **Step 4:** 将 v1.2 标为归档并指向 v1.3。

### Task 4: 生成 API v2.1 派生契约

**Files:**
- Create: `D:/M2开发/M3教师端/M3_API接口文档_v2.1.md`
- Modify: `D:/M2开发/M3教师端/M3_API接口文档.md`

**Interfaces:**
- Consumes: 产品 SSOT 的 8 条推荐入口、现有 M2 REST 资源、Teacher Application Services、Capability Gateway。
- Produces: P0/P1 端点目录、核心请求响应 Schema、状态机、幂等、错误和兼容策略。

- [ ] **Step 1:** 定义 P0 闭环端点和 `/api/ai/capabilities/{capability}` 内部入口。
- [ ] **Step 2:** 定义 P1 资源管理端点，优先复用 `/api/classes`、`/api/files`、`/api/courses`、`/api/kb`。
- [ ] **Step 3:** 定义 Artifact、确认闸、任务轮询和业务降级信封。
- [ ] **Step 4:** 明确不新增科研端点和不重复新增 `/tools/learning-summary`。
- [ ] **Step 5:** 将旧 API 文档标为归档并指向 v2.1。

### Task 5: 生成前端指南 v2.1

**Files:**
- Create: `D:/M2开发/M3教师端/M3_前端开发指南_v2.1.md`
- Modify: `D:/M2开发/M3教师端/M3_前端开发指南.md`

**Interfaces:**
- Consumes: 7 个一级工作区、API v2.1、Prototype v2.1。
- Produces: 7 个 Shell 路由、Store 边界、Artifact 编辑流、状态与降级 UI。

- [ ] **Step 1:** 用 `/teacher/today|prep|assign|grading|classroom|classes|resources` 替换 16 条旧路由。
- [ ] **Step 2:** 定义 `teacherToday`、`teacherContext`、`lessonArtifacts`、`assessment`、`grading`、`classroom`、`resources` Store。
- [ ] **Step 3:** 定义“发生了什么→依据→行动”、确认闸、轮询和离线/降级状态。
- [ ] **Step 4:** 将旧前端指南标为归档并指向 v2.1。

### Task 6: 调研矩阵与全局一致性验收

**Files:**
- Modify: `D:/M2开发/M3教师端/教师端AI管家_产品与技术实现说明_v2.2.md`
- Verify: `D:/M2开发/M3教师端/教师端AI管家_高中教师高保真原型_v2.1.html`

**Interfaces:**
- Consumes: 已核验的 26 个 GitHub 仓库、教师工作负担研究和 5 个主流产品。
- Produces: “借什么/不借什么/如何落到 M3”的技术选型矩阵和一致性报告。

- [ ] **Step 1:** 写入 26 项 GitHub 技术栈与采用结论。
- [ ] **Step 2:** 写入教师痛点到产品决策的证据映射。
- [ ] **Step 3:** 检查标准工作流名、7 个 Capability、7 个路由和 F12/F14 边界。
- [ ] **Step 4:** 检查所有 Markdown 链接指向存在文件。
- [ ] **Step 5:** 输出修改清单、验证证据与保留风险。

