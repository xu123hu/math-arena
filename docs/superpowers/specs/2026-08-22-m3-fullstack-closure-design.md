# M3 教师端全栈真实闭环设计

> 日期：2026-08-22
> 状态：已获用户批准，进入实施准备
> 上游：教师端产品 SSOT v2.1、技术说明 v2.2、API v2.1、前端指南 v2.1
> 目标覆盖：用户最新要求“除外部 AI 工作流外，其余功能全部完善；七项 AI 能力均可依靠本地降级完成闭环”

## 1. 决策与约束覆盖

本轮采用“结果优先、纵向闭环”的全栈收口方案。旧主提示词要求 `D:\frontend` 只读，但当前真实前端包含 `mock-001`、固定班级、固定待办数和“真实数据不足时用 mock 补齐”等展示逻辑；仅修改后端无法满足“页面数据真实”。用户已明确批准全栈修改，因此本设计对旧约束作如下最小覆盖：

- 允许修改 `D:\frontend`，但只删除真实模式的假数据、接通现有 API/Store、补齐真实空态和错误态；不重做视觉设计。
- 外部星辰工作流不作为本轮完成门槛；未配置、禁用、未验证、超时、限流或 Schema 非法时，七项 Capability 必须走本地业务降级。
- 继续复用 FastAPI、SQLAlchemy、PostgreSQL、Vue 3、Pinia 和 Butler Kernel v2；不引入第二套 Agent Runtime 或通用 LMS 框架。
- 教师端不实现科研验证、论文评审、建模教练、Lean 或 `review_paper`。
- 当前两个仓库均有大量既有未提交修改。所有补丁和提交只使用精确路径，不清理、覆盖、暂存或提交无关文件。
- 按主提示词要求直接在 `D:\math-arena` 与现有 `D:\frontend` 施工，不创建替代项目目录。

## 2. 完成定义

“全部完善”按可验证业务结果定义，不按页面数量或接口存在性定义：

1. 教师账号登录后直接进入教师端，学生账号进入学生端，角色切换和越权拒绝稳定。
2. 七个教师工作台只展示真实 API 数据；无数据时展示空态，绝不补静态课程、人数、分数、资源或批改记录。
3. 教师可完成教案草稿、编辑、确认、课件和讲题卡的本地降级链。
4. 教师可从真实题库生成题集、确认、创建作业草稿并发布；未发布作业学生不可见。
5. 学生可查看已发布作业及题目并提交；提交必须校验班级成员、作业目标、发布状态和题组归属。
6. 主观题进入教师批改队列；本地能力生成建议后，教师 accept/override 才写正式分、评语、提交汇总和学情。
7. 学生能读取教师确认后的正式成绩与评语；教师 Today/班级洞察随提交和确认结果变化。
8. 教师课堂模式持久化，跨请求/进程可读，具有 TTL、幂等和审计；已确认学生读取同一状态。
9. 教师资源真实上传、解析、理解和引用；只有显式发布到班级的资源对学生可见。
10. 七项 Capability 在全部外部工作流不可用时仍返回可编辑、可确认、来源可追踪的 `degraded=true` Artifact 或真实本地结果。

## 3. 现状证据与主要缺口

- 当前教师演示账号最初被自动注册为学生，登录 API 又无条件取第一角色；演示数据已临时纠正，但默认角色选择仍需回归测试保护。
- `daily_questions` ORM 已要求 `user_id`，历史迁移却只有全站唯一 `date`，真实 `/api/student/daily-plan` 返回 500。
- `classroom.py` 使用进程内 `_CLASSROOM_STATE`，重启或多 worker 后状态丢失；迁移也没有课堂状态表。
- 现有后端 E2E 到“发布作业”即结束；没有真实覆盖学生提交、教师 override、学生成绩读取和洞察更新。
- `practice/submit` 接受 `assignment_id`，但没有完整校验 assignment 是否发布、是否定向当前学生、quiz 是否匹配。
- 批改服务能保存建议分和终评分，但测试种子让教师同时充当学生，不能证明真实角色与班级联动。
- Today 把 Assignment deadline 当成下一节课时间，语义错误；缺少真实课表时应返回空态。
- 教师资源处理仍是最小任务结果，未形成“上传文件 → 本地提取 → 来源定位 → Artifact → 发布给学生”的闭环。
- 前端 Today、Classes、Grading、Resources 明确存在静态 mock 兜底；浏览器真实模式出现的“7 班、12 份待批”等与数据库不一致。
- 七个教师工作流当前 4 个配置、0 个验证、0 个可用；这不应阻塞本轮本地闭环。

## 4. 总体架构

采用六个可独立验收的纵向切片：

```text
身份/班级范围
      ↓
真实 Today 与班级上下文
      ↓
教案/题集 Artifact（本地降级）
      ↓ 教师确认
Assignment draft → published
      ↓
学生可见 → 学生提交 → Submission/SubmissionItem
      ↓
本地预批改 → 教师 accept/override
      ↓
正式成绩/评语 → 学生结果 → Mastery/教师洞察

课堂模式：教师 WRITE → PostgreSQL TTL 状态 → 学生 READ
资源链：File → 本地解析/引用 Artifact → 教师发布 → 学生 READ
```

外部工作流只位于 Capability Gateway 的可选分支：

```text
Capability request
  → scope/policy
  → workflow available? ─ yes → adapter → schema validation
                      └─ no/error → deterministic local fallback
  → draft Artifact (engine=local, degraded=true when fallback)
  → teacher confirmation
  → formal business write
```

## 5. 数据模型与迁移

新增独立 Alembic revision，不改写历史迁移。

### 5.1 `daily_questions` 兼容修复

- 新增 nullable `user_id` 外键，保留历史全站题记录而不删除或错误归属。
- 删除旧的单列 `date` 唯一约束，新增 `user_id + date` 的部分唯一索引（仅 `user_id IS NOT NULL`）。
- ORM 将遗留行视为兼容数据；新写入一律要求真实用户 ID。
- 日计划查询只读取当前用户行；无行时为当前用户生成，不再触发 UndefinedColumn。

### 5.2 持久课堂状态

新增 `classroom_modes`：

- `class_id` 唯一、`enabled`、`lesson_id`、`settings`、`started_by`、`expires_at`、`version`、时间戳。
- 启停采用事务 upsert 和乐观版本；`expires_at <= now` 统一序列化为关闭。
- `teacher_actions` 继续记录操作人、幂等键和脱敏变更摘要。

### 5.3 课表与 Today

不再使用作业截止时间伪装上课时间。Today 的 `next_lesson` 只来自带真实 `starts_at` 的课程/教案安排；若当前系统没有课表数据，返回空对象和明确 `schedule_missing=true`。作业截止只进入 `deadlines`。

### 5.4 资源发布

复用现有 File、TeacherTask 与 TeachingArtifact，不新建平行文件系统。文档解析/理解形成带 `resource_id`、来源页码和警告的 Artifact；Artifact 被教师发布后，学生端按班级 scope 读取。未发布、非本班或 owner 不匹配时不可见。

## 6. 核心业务规则

### 6.1 身份与班级范围

- 教师接口严格要求 `active_role == teacher` 且角色绑定存在。
- 学生只能读取已确认加入班级后定向给该班/本人且状态为 published 的内容。
- 所有实体访问从实体反查 class_id，不信任客户端提交的 class_id。
- 双师只允许 owner 或 confirmed `member_role=teacher` 共享班级；审计记录实际操作人。

### 6.2 作业发布与学生提交

- quiz_set Artifact 必须 confirmed 才能物化 Quiz 和 Assignment draft。
- publish 必须幂等、带教师确认并写审计。
- 学生提交前校验：Assignment 存在、published、未过关闭状态、目标命中、班级成员已确认、请求 quiz_id 与 Assignment.quiz_id 一致。
- `client_submit_id` 对同一学生幂等；重放返回首次结果，不重复写错题、掌握度或打卡。
- 客观题按现有规则/SymPy 判分；主观题或无法可靠判分的题进入 `pending_review`。

### 6.3 预批改、确认与成绩回写

- suggest 只写 suggested_score、rationale、feedback 草稿和 grading_suggestion Artifact，不写正式 score。
- accept 使用建议分；override 必须提供 final_score。二者均保存原建议、教师终值、反馈、确认人和时间。
- confirm 在同一事务重算 Submission.total_score/status、执行一次 mastery 更新并写 TeacherAction。
- 学生作业详情以加法兼容方式返回最新 submission、逐题 final_score/feedback 和总分。
- 教师聚合只消费已确认终值，不把未确认建议算入学情。

### 6.4 Today 与洞察

- 下一节课、截止任务、待批和洞察分别使用独立真实来源。
- 洞察 evidence 由确定性 SQL 生成；本地文本模板只负责可读摘要，不编造样本量或百分比。
- 无数据返回空数组和原因字段；前端显示“暂无数据/尚未接入”，不回退模拟值。

### 6.5 课堂模式

- 教师启停属于 WRITE，要求 idempotency key、班级 scope 和审计。
- 学生轮询同一数据库状态；TTL 到期自动关闭。
- 无视频/实时事件源时参与度为空且 `degraded=true`，不伪造同步人数或回看热点。

### 6.6 资源

- multipart 文件通过既有 File 服务保存，检查 owner、大小和 MIME。
- 本地预处理至少完成可支持格式的文本提取、分段、页码/段落定位和稳定错误码。
- 本地理解至少返回摘要、关键概念、教学建议、来源定位和不确定项；无法解析时保留原文件并返回可恢复状态。
- 发布前保持教师私有；发布后按 class scope 对学生可见。

## 7. 七项本地降级契约

| Capability | 本地结果 | 必须验证 |
|---|---|---|
| `adapt_lesson` | 45 分钟结构化课堂时间线，合并教师材料和真实班级洞察 | 时长合计、来源、可编辑内容 |
| `create_slides` | 可编辑 slide 数组，来自 confirmed 教案 | 标题/要点/讲者备注/来源，不返回空页 |
| `create_quiz` | 真实题库检索、去重、题型和数量护栏 | 不足明确失败，不重复凑数 |
| `suggest_grade` | 客观规则/SymPy；主观题评分点建议或明确人工复核 | 永不自动正式计分 |
| `explain_problem` | 题目重述、关键观察、分步解法、易错点和追问 | 不返回空 steps，不声称形式化证明 |
| `preprocess_course` | 本地文件解析、分块、知识点候选和来源定位 | 任务状态真实，失败可恢复 |
| `understand_document` | 摘要、关键概念、教学建议、问答和引用 | 引用可追踪，不确定项显式标记 |

本地降级产物统一：`engine=local`、`degraded=true`、`warnings` 说明外部能力不可用、`validation` 记录确定性检查。降级产物仍须经过教师确认。

## 8. 前端真实性修改

不改变现有布局和样式，只修正数据来源与交互：

- Today 完全读取 `teacherToday` Store；删除固定课程、`grading + 8` 和静态班情洞察。
- Classes 从 `/api/classes/mine` 和 insights API 构造班级上下文；删除固定“高二（7）班”。
- Grading 从真实 queue 选取路由项或首个待批项；删除 `mock-001` 和模拟详情。
- Resources 只展示真实 Store 列表；删除“不足 4 条用 mock 补齐”。
- Prep、Assign、Classroom 的班级选择来自真实班级列表；不内置不存在的 class ID。
- `VITE_USE_MOCK=1` 仍允许独立展示测试，但默认真实模式不得导入或消费 teacher mock data。
- 为七页统一补 loading、empty、degraded、error、permission 状态；错误不回填假数据。
- 学生作业页展示真实题目、提交状态、教师最终成绩与评语。

## 9. 错误、幂等和安全

- 稳定错误：validation、unauthorized、role_denied、class_scope_denied、not_found、version_conflict、confirmation_required、capability_degraded、capability_unavailable。
- 外部异常、SQL、路径、密钥和供应商原文不得进入响应、Prompt、Ledger 或前端日志。
- 同一正式动作重试复用同一幂等键；重放返回首次结果。
- 任何 AI/本地建议都不能自动发布作业、写正式成绩或控制课堂。
- 测试覆盖跨教师、未确认成员、学生猜 UUID、非本班资源和提交伪造。

## 10. TDD 与验收策略

每个纵向切片遵循 RED → GREEN → REFACTOR：

1. 先增加失败的迁移/数据库契约测试，证明 daily-plan 和课堂持久化缺口。
2. 增加真实双账号 E2E：发布 → 学生读取 → 学生提交 → 教师建议/override → 学生结果 → 洞察更新。
3. 增加七项工作流全部禁用的本地降级契约测试，断言内容非空、degraded、确认闸有效。
4. 增加资源上传/解析/理解/发布/学生读取的真实测试。
5. 增加前端 Store/页面测试，断言真实模式不存在 mock 文案和 mock ID。
6. 浏览器用真实 `13900001001` 教师和 `13900001002` 学生执行完整链路。

最终门禁：

- M3 聚焦、Butler、工作流和学生联动测试全绿。
- 完整后端 pytest 退出码 0。
- Alembic 单 head；临时 PostgreSQL 从空库 upgrade 成功，现有开发库 upgrade 成功。
- Ruff、Mypy 本轮文件、`git diff --check` 通过。
- 前端 Vitest、typecheck、build 和真实模式 E2E 通过。
- 浏览器七个教师页面无静态假数据；学生每日计划不再 500。
- 外部七工作流 `available=0` 时完整教学闭环仍通过。

## 11. 实施顺序

1. 迁移和数据契约：daily questions、课堂持久化、真实课表空态。
2. 作业可见性与安全提交。
3. 批改确认、成绩/评语回写和学情更新。
4. 七项本地降级内容收口。
5. 资源解析、理解和发布闭环。
6. 前端七页移除真实模式 mock，接真实 Store。
7. 真实浏览器双角色 E2E、全量回归和干净快照验收。

## 12. 非目标与保留风险

- 不要求本轮打通或验证付费外部 AI 工作流。
- 不实现实时 WebSocket 课堂参与度；数据库轮询 + TTL 是本轮可靠基线。
- 不新增科研端功能。
- 高保真原型文件在 SSOT 指定目录缺失；现行 Vue 页面与前端指南作为视觉基准，本轮不改视觉。
- 本地文档解析质量受文件类型限制；不支持的格式必须明确失败或要求人工校对，不能伪装理解成功。
