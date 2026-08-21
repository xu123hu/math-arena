# M3 教师端全栈审查报告

审查日期：2026-08-21  
审查方式：独立、只读、证据优先；未修改、清理、暂存、stash、reset、checkout 或提交任何既有业务文件。唯一写入文件为本报告。  
审查对象：后端 `D:\math-arena` 的 M3 提交，以及前端 `D:\frontend` 的 M3 提交；并行的 M2 阶段 6 和管理端未提交改动不纳入 M3 结论。

## 1. 执行摘要与结论

结论：M3 教师端当前为 **后端 Conditional Go、前端 Conditional Go、联调 No-Go、进入集成演示 No-Go**。七路由已出现，七能力和七工作流也有名称、注册表和本地降级骨架，但尚未形成可验证的“SSOT → 后端 OpenAPI → 前端真实调用 → Artifact/确认/审计”闭环。

最影响上线或演示的事实：

- 后端教师开关默认关闭；`M3_ENABLE_TEACHER=true` 时当前 OpenAPI 有 32 个教师路径，默认 profile 不挂载教师路由。
- 后端角色检查允许 `active_role=student` 且 `roles` 包含 `teacher` 的令牌进入教师端；这是角色越权风险。
- `GET /api/teacher/grading/{submission_item_id}` 未按班级范围校验，已知 submission UUID 的教师可读取不属于其班级的提交项。
- 前端核心写入契约普遍与后端不一致：确认/发布/归档缺 body，作业字段不匹配，资源上传把 JSON 当文件上传，课堂状态请求了后端不存在的 GET，grading 确认缺少 `suggestion_id` 和 `version`。
- 后端 Artifact 状态机和题库不足保护的 M3 测试存在真实失败；完整后端测试为 1279 通过、11 失败、6 跳过。
- 七工作流在注册表中存在，但 Xingchen 适配器用错误的同步/异步调用签名，配置可用时也无法按当前 provider 契约成功调用；本地降级能力多为占位或最小输出。
- 前端 `/api/teacher/butler/chat` 不在当前后端 OpenAPI，也不在 M3 API SSOT 中；它是前端自造的兼容/演示通道，不应作为正式契约。其“确认联网执行”按钮只关闭弹层和 toast，没有发出确认后的执行请求。

本次按严重性记录 **14 项发现：Critical 4、Important 8、Minor 2**。F14 验证推导、Lean、论文评审未进入教师端路由、能力或工作流；该边界核对通过。

## 2. Git 基线、范围和脏工作区隔离

### 后端

- 仓库：`D:\math-arena`
- branch：`feat/backend-m1`
- HEAD：`6dc58f00eb8abd56d974671126723cebd50b551e`
- M3 主提交：`6d55c3d feat: add M3 teacher core models and migration`、`6dc58f0 feat: add M3 teacher backend services, routes, registry and tests`
- 主要审查范围：`5054325..6dc58f0`
- 范围 diff：36 files，约 5001 insertions、2 deletions；`git diff --check 5054325..6dc58f0` 通过。
- 当前工作区存在大量 M/D/??，包括 M2 阶段 6、CI、`apps/web` 和诊断文件；未使用工作区状态作为 M3 完成证据，也未对其做任何操作。

### 前端

- 仓库：`D:\frontend`
- branch：`master`
- HEAD：`f1b2646172d5c4fed5142a8337f4dab9f2c79375`
- M3 前端范围：`4d41054..f1b2646`，71 files，约 5504 insertions、179 deletions；M3 主要提交链包含 `540bc20` 起至 `59f96c0`、`8e93b05`、`f4725bc`、`e215c6a`、`26d9447`、`a0f04d3`、`cd9ebc9`、`fb1978d`、`cce530f`、`682eddb`、`46b8e0b`、`f1b2646`。
- 当前未提交的 `App.vue`、`api/index.js`、`nav.js`、`router/index.js`、`src/components/admin`、`AdminLayout.vue`、`src/pages/admin` 等为并行管理端工作，未混入 M3 结论。

未发现适用于两个仓库根目录的额外 `AGENTS.md`；只读检查了仓库下可见指令文件。M3 SSOT 已阅读：README、产品需求、边界迁移说明、产品与技术实现、API 文档、工作流指南、前端指南、高保真原型和竞品/开源架构调研。执行日志仅作线索，未作为完成证据。

## 3. SSOT、后端、前端端点级契约矩阵

当前启用 `M3_ENABLE_TEACHER=true` 后，以 OpenAPI 和代码为准的后端实际暴露 32 个 `/api/teacher/*` 路径；没有 `/api/teacher/butler/chat`，没有 GET classroom-mode，也没有教师端 F14 研究路由。统一成功辅助函数 `D:\math-arena\services\api\app\domains\teacher\router.py:55-56` 只返回 `code/message/data`，缺少 SSOT 要求的 `request_id`。

| SSOT 能力/接口 | 后端当前实际 | 前端当前实际 | 判定 |
|---|---|---|---|
| `GET /teacher/today` | 存在，`data` 为今日聚合；无班级时可降级 | `TeacherTodayView` 按 `TeacherTodayData` 使用 | Partial；日期/下一节课语义仍需收敛 |
| `GET /teacher/classes/{id}/insights` | 返回 `data: { insights: [...] }`，`router.py:81-90` | `src/api/teacher/classes.ts:5-6` 声明为数组，`TeacherClassesView.vue:58` 直接赋给数组 | Broken contract |
| `POST /teacher/lessons/adapt` | `lessons.py:51-99` 只返回 `artifact_id/status/degraded` | `src/api/teacher/lessons.ts:5` 和 `lessonArtifacts.ts:15-24` 期待含内容的 `TeacherArtifact` | Partial/不可展示草案内容 |
| `POST /teacher/lessons/{id}/apply-insight` | `router.py:162-174` 接收 `insight_id`，但未按 ID 查询，只把可选 summary 传入 | 页面 `TeacherClassesView.vue:75-76` 只 toast，不调用该接口 | UI 假动作，后端也不可信 |
| `POST /teacher/lessons/{id}/slides` | 要求 `version`，返回 `artifact_id/status/outline`，`lessons.py:170-203` | `lessons.ts:10-11` 期待 `{task_id}`，页面立即轮询任务 | Broken contract |
| `POST /teacher/lessons/{id}/explainer` | 路由在 `router.py:183-192` 传 `class_id=None`，服务要求班级范围，`lessons.py:215-243` | 同样期待 `{task_id}` | Broken/越界风险 |
| `POST /teacher/quizzes/generate` | `assessment.py:42-126` 建 Artifact，但只返回 `artifact_id/status/question_count` | `assessment.ts` 和 Assign 页面按含题目内容的 Artifact 使用 | Partial；真实预览无法由当前响应构建 |
| `POST /teacher/assignments` | 要求 `artifact_id`、`client_assignment_id`，且 Artifact 必须 confirmed，`assessment.py:163-207` | `TeacherAssignView.vue:113` 发 `class_id/title/quiz_set` | 422/确认链断裂 |
| assignment publish/close/archive | 后端 body 是必填请求模型，`router.py:228-260` | `assignments.ts:10-14` body 为 `undefined` | 422 |
| `GET /teacher/grading/queue` | 返回 `data: { queue: [...] }`，`router.py:279-281` | store 按数组接收 `grading.ts:6-16` | Shape mismatch |
| `GET /teacher/grading/{id}` | 只检查 teacher role，`router.py:296-305` 直接 `db.get`，忽略 `class_id` | 前端无 class scope 参数 | Critical scope gap |
| grading confirm | 后端要求 suggestion/version 等字段 | `grading.ts:30-35` 只发 decision/final_score/feedback | 422 或状态错误 |
| batch confirm | 后端每项没有 Idempotency-Key，异常直接 `str(exc)`，`router.py:324-341` | 前端虽有批量 API，但收不到稳定错误契约 | Important |
| `POST /teacher/classes/{id}/classroom-mode` | 只有 POST，`router.py:104-119` | `classroom.ts:6-8` 另外调用 GET 状态 | GET 404/405 |
| video insights | 后端返回降级空聚合；不伪造视频数据 | Classroom 页面可显示 degraded | Conditional/可接受降级 |
| Artifact get/update/actions | action body 必填；动作响应含 artifact | `artifacts.ts:8-12` confirm/publish/archive 无 body | 422 |
| resources list/upload/preprocess/understand | upload 是 multipart `UploadFile`；后三者 body 必填；服务多为 task 入队/占位 | `resources.ts:7-11` 发 JSON/无 body；页面 `TeacherResourcesView.vue:66-70` 不传文件 | Broken/Mock-only live flow |
| tasks | 后端有 GET/cancel，但资源链没有真实执行者闭环 | slides/explainer 误将同步 artifact 当 task | Partial |
| `GET /teacher/capabilities`、`POST /teacher/capabilities/{capability}` | 列出 7 个能力；POST 直达 `run_capability`，`router.py:486-532` | 前端主页面主要走各业务 API | Architecture mismatch |
| `/teacher/butler/chat` | 当前 OpenAPI 不存在 | `src/api/teacher/butler.ts:11-14` 调用；`.workbuddy/m3-backend-contract-gaps.md:22` 当时标为非正式 | Frontend self-made compatibility route |

### 请求/响应和错误边界

- SSOT 要求 `{code,message,data,request_id}`；成功响应缺 `request_id`。验证错误和全局异常在 `D:\math-arena\services\api\app\main.py:97-138` 使用 `requestId` camelCase，且异常 envelope 也不稳定。
- 前端 `src/api/client.js:1-110` 能识别统一 `code`，但不能弥补后端缺字段和业务 data shape；Mock server 对多个错误契约放宽，掩盖了真实问题。
- OpenAPI 中错误模型、确认模型和幂等字段以当前 FastAPI 生成结果为准；不能以旧日志的“接口已对齐”表述替代真实请求测试。

## 4. 七路由、七能力、七工作流状态矩阵

状态含义：Implemented=可按 SSOT 端到端验证；Partial=存在代码但契约、范围、执行或降级仍不完整；Mock-only=只有 Mock 演示可走通；Missing=不存在；Out-of-scope=按边界不应属于教师端。

### 七路由

| 路由 | 状态 | 证据/原因 |
|---|---|---|
| `/teacher/today` | Partial | 后端聚合和前端页面存在；局部数据/下一节课语义不完整 |
| `/teacher/prep` | Partial | adapt/Artifact 骨架存在，但响应缺内容、slides/explainer task 契约不符 |
| `/teacher/assign` | Partial | 题目生成与确认 UI 存在；创建/发布真实请求字段不匹配 |
| `/teacher/grading` | Partial | 状态和确认 UI 存在；scope、字段、幂等、响应 wrapper 有问题 |
| `/teacher/classroom` | Partial | POST 控制和视频降级存在；状态 GET 缺失，状态为进程内字典 |
| `/teacher/classes` | Partial | insights 后端存在；前端数组 shape 错，apply 按钮不调用后端 |
| `/teacher/resources` | Partial/Mock-only | 后端路径和资源模型存在，实际上传/预处理/理解链未接通，Mock 才能完成演示 |

### 七能力

七项名称在 `D:\math-arena\services\api\app\domains\teacher\capability_gateway.py:24-34` 中存在，并有本地 builder，但没有一项在本次证据标准下可判定为端到端 Implemented。

| 能力 | 状态 | 结论 |
|---|---|---|
| `adapt_lesson` | Partial | 有 scope、草稿 Artifact、本地降级；HTTP 直接绕过正式 Butler 执行链，响应过窄 |
| `create_slides` | Partial | 本地 outline builder 存在；没有真实 task 契约，Xingchen 路径有调用错误 |
| `create_quiz` | Partial | 题库优先/去重骨架存在；不足量测试失败，响应不含题目 |
| `suggest_grade` | Partial | 草稿建议路径存在；部分本地结果是零分/低置信度占位，最终评分仍需确认 |
| `explain_problem` | Partial | 本地 builder 输出空步骤占位；explainer 路由传空班级 |
| `preprocess_course` | Partial | 能创建 queued task，但没有实际执行消费者/结果闭环 |
| `understand_document` | Partial | 能创建 queued task，但没有真实文档理解结果闭环 |

### 七工作流

`workflow_adapter.py:17-25` 映射了七条 `wf_*` 工作流，注册表也有对应工具；但 `workflow_adapter.py:70-117` 的 provider 调用与 `D:\math-arena\services\api\app\providers\xingchen.py:546-553` 不一致：前者同步调用 `_xc_run(flow_name, positional_input, timeout_s=20)`，后者是 async 且要求关键字 `uid`、`parameters`、`read_timeout`。因此七项均为 Partial：配置不可用时可降级，配置可用时当前代码无法按 provider 签名成功执行。

| 工作流 | 状态 |
|---|---|
| `wf_lesson_plan` | Partial |
| `wf_ai_ppt` | Partial |
| `wf_explainer_script` | Partial |
| `wf_smart_quiz` | Partial |
| `wf_solution_pregrade` | Partial |
| `wf_course_preprocess` | Partial |
| `wf_doc_understand` | Partial |

F14 验证推导、Lean、论文评审：**Out-of-scope，核对通过**。当前教师 OpenAPI 没有研究路由；前端 M3 路由、导航和代码扫描也没有将 F14 混入教师工作台。

## 5. 鉴权、角色、班级 scope、确认、幂等、敏感信息和 F14 边界

### 已确认的正向项

- 前端 `D:\frontend\src\router\index.js:30-60` 有七条教师路由和 activeRole teacher 守卫。
- 后端教师路由均依赖 `get_current_user`，并调用教师角色/班级 scope 相关函数；跨教师班级的主要服务路径有拒绝测试。
- Registry 中工具均为 teacher-only，生成/写入工具带风险和幂等元数据；可见性静态检查得到 teacher 可见、student 不可见。
- 高风险 UI 有二次确认：教案确认、作业发布、课堂启动/停止、grading 接受/覆盖；Artifact 数据模型保留版本和状态字段。
- `useChat` 只在 capability 明确允许时发送 `web_search_opt_in`，缺失或 false 时 fail-closed；对应 Vitest 覆盖通过。
- provider 原始响应不直接回传；视频无源时返回明确 degraded 空聚合而不是伪造数据。

### 发现

- `D:\math-arena\services\api\app\domains\teacher\scope.py:36-47` 的条件是 `active_role != teacher and teacher not in roles` 才拒绝。复现 `active_role=student, roles=[student,teacher]` 可通过；这与“active role 必须为 teacher”的 SSOT/注释不一致。
- `router.py:296-305` 的 grading detail 只按 UUID 读取 `SubmissionItem`，不调用班级成员校验；这是实际数据泄露面。
- `capability_gateway.py:150-221` 收到任意 `scene` 和任意内部 `payload`，没有在该入口强制 teacher/class scope，也没有经过正式 Registry/Policy/Executor；`router.py:495-510` 直接调用它。Registry 的存在不能证明 HTTP 已使用 Registry。
- Artifact action、assignment action、grading confirm 的 `client_request_id`/`Idempotency-Key` 没有统一强制；batch confirm 明确传 `None`，还把异常字符串放入响应。
- Classroom `_CLASSROOM_STATE` 在 `D:\math-arena\services\api\app\domains\teacher\classroom.py:32-94` 是进程内全局状态，不能跨 worker/重启共享，不能作为可靠的课堂控制审计状态。
- 目前没有发现教师端 F14 越界；该项保持排除。

## 6. 测试、迁移、OpenAPI 和构建证据

| 验证 | 结果 |
|---|---|
| 后端 Butler 回归：`tests/test_butler_compat_v2.py`、`test_butler_kernel_v2_closure.py`、`test_butler_kernel_v2_ledger_semantics.py`、`test_butler_runtime.py` | 49 passed，10 warnings，退出码 0；使用仓库 `.venv`，系统 Python 因缺 `pydantic_ai` 不能收集 |
| 后端 M3 聚焦测试 | 46 passed，7 failed，19 warnings，退出码 1；失败涉及 Artifact 状态/幂等、题库不足、assignment、grading、lesson version；部分同时出现 asyncpg loop/MissingGreenlet 痕迹 |
| 后端完整 `pytest -q` | 1279 passed，11 failed，6 skipped，55 warnings，退出码 1；失败不是只发生在测试收集，至少包含 `test_unconfirmed_cannot_publish`、`test_confirm_then_publish`、`test_confirm_idempotent_replay`、`test_generate_quiz_insufficient_fails`、`test_new_assignment_is_draft_and_publish`、`test_full_backend_flow`、`test_confirm_accept_sets_final_and_idempotent`、`test_apply_insight_creates_new_version` |
| `compileall` + M3 app/tests `ruff check` | 通过，退出码 0 |
| mypy/pyright | 未运行：当前环境未安装，不能以“类型检查通过”表述 |
| `alembic heads` | `m3_001_teacher_core (head)`，单 head 通过 |
| 全新临时 SQLite `alembic upgrade head` | 在临时库失败于首个 PostgreSQL `CREATE EXTENSION IF NOT EXISTS pgcrypto`；未触碰真实开发/生产库。由于没有可安全使用的临时 PostgreSQL，本次不能宣称完整 upgrade 通过；这更准确地说明迁移是 PostgreSQL-specific |
| 启用 M3 的 OpenAPI | 读到 32 个 `/api/teacher/*` path；无 Butler chat、无 classroom GET、无教师 F14 路由 |
| 前端 `npm run test:run` | 10 files、54 tests passed，退出码 0 |
| 前端 `npm run typecheck` | 通过，退出码 0 |
| 前端 `npm run build` | 通过，退出码 0；Vite 219 modules，有 dynamic import 警告 |
| 前端 `VITE_USE_MOCK=1 ... npm run build` | 通过；构建产物 JS 未发现 `mock-token`、`teacherServer`、`VITE_USE_MOCK` 等 mock 标记 |
| 前端 `npm run e2e:mock` | 22 passed，退出码 0；全部为 Mock dev server |
| 前端真实模式 `npm run e2e` | 22 failed，退出码 1；准确原因是 `http://localhost:5176` connection refused，真实模式未启动 webServer/后端，不能视为业务断言失败或真实链路通过 |

## 7. 发现清单（按严重性）

### Critical

**C-01 角色判定可被“角色列表包含 teacher”绕过 active role。**  
证据：`D:\math-arena\services\api\app\domains\teacher\scope.py:36-47`。触发方式：使用有效 JWT claims `active_role=student`、`roles=[student,teacher]` 请求任一教师路径；`require_teacher_role` 返回 teacher UUID。影响：非当前激活教师身份可进入教师 API。建议：严格要求 `active_role == teacher`，再独立检查角色声明与权限，补充反例测试。

**C-02 能力 HTTP 入口未走正式 Registry/Policy/Executor，且没有强制 class scope。**  
证据：`D:\math-arena\services\api\app\domains\teacher\router.py:486-532` 直接调用 `run_capability`；`capability_gateway.py:150-221` 接受任意 scene/payload。触发方式：携带教师 token 直接 POST `/api/teacher/capabilities/{capability}`，传入未授权 class_id/scene。影响：SSOT 要求的 teacher-only、班级范围和统一 Butler Kernel 执行链无法由该入口证明；后续新增能力容易绕过 Policy。建议：HTTP 只进入 Registry/Policy/Executor，统一生成 context、scope、审计和幂等；拒绝任意 scene/payload。

**C-03 grading detail 缺班级范围校验，可读取其他班级提交。**  
证据：`D:\math-arena\services\api\app\domains\teacher\router.py:296-305`。触发方式：教师 A 取得教师 B 班级的 `submission_item_id` 后 GET `/api/teacher/grading/{id}`；代码只做 teacher role 和 UUID 存在性检查。影响：学生答案、建议分数和反馈跨班级暴露。建议：通过 assignment/submission 反查 class_id 并调用 `assert_teacher_in_class`；`class_id` 查询参数若存在必须与实体一致。

**C-04 前后端核心写入契约不兼容，真实教师主链无法完成。**  
证据：后端 `router.py:228-260, 308-341, 398-445`；前端 `D:\frontend\src/api/teacher/assignments.ts:8-14`、`artifacts.ts:8-12`、`grading.ts:10-14`、`resources.ts:7-11`。触发方式：真实模式执行确认 Artifact、发布作业、确认 grading 或上传资源。前端省略后端必填 action body，assignment 发 `quiz_set` 而后端要求 `artifact_id/client_assignment_id`，resource 发 JSON 而后端要求 multipart，grading 缺 `suggestion_id/version`。影响：大量 422/404，不能完成确认、发布、评分、资源理解闭环。建议：先冻结一份 OpenAPI-generated/contract-tested schema，再逐接口修正请求与响应；用真实后端 smoke 替代 Mock-only E2E。

### Important

**I-01 M3 默认 profile 不挂载教师路由。** 证据：`D:\math-arena\services\api\app\config.py:117-120` 默认 false，`main.py:224-229` 条件挂载。触发方式：不设置 `M3_ENABLE_TEACHER=true` 启动 API。影响：集成环境若漏配变量，七路由全部不存在；进入演示只能 Conditional。建议：为环境配置、启动检查和演示脚本增加显式 profile smoke，并保留默认关闭的 M2 兼容策略。

**I-02 统一 envelope 的 request id 不符合 SSOT。** 证据：`router.py:55-56`；`main.py:97-138`。触发方式：任一成功或异常教师请求检查 JSON。影响：前端/日志无法稳定按 SSOT 字段关联；异常 envelope 还存在 `requestId` 与缺 `data` 的差异。建议：统一 `request_id`，所有成功/业务错误/未处理异常走同一响应模型。

**I-03 Xingchen adapter 的调用签名和 async 语义错误。** 证据：`D:\math-arena\services\api\app\domains\teacher\workflow_adapter.py:70-117` 对比 `providers/xingchen.py:546-553`。触发方式：启用 Xingchen、配置 flow map 后执行任一七工作流。影响：provider path 进入异常/降级，七工作流无法证明可执行。建议：按 provider 的 `await run_workflow(flow, uid=..., parameters=..., read_timeout=...)` 封装，并用模拟 provider 做成功/超时/降级三态测试。

**I-04 Artifact/assignment 状态机实现与自身 M3 测试预期不一致。** 证据：后端测试失败：`tests/test_m3_teacher_artifacts.py:57,67,109,121`、`tests/test_m3_teacher_assessment.py:73,87`；`lessons.py:99`/`assessment.py:126` 也返回过窄。触发方式：未确认 Artifact publish、confirm、archive、相同幂等 key replay、题库不足、confirmed quiz 创建 assignment。影响：高风险动作的确认/幂等/拒绝语义不可信；完整后端测试退出码 1。建议：先修状态转换与幂等存储/事务，再以每个错误码和版本冲突为契约测试基线。

**I-05 Butler chat 是前端自造路由，且确认按钮不执行确认后的动作。** 证据：`D:\frontend\src/api/teacher/butler.ts:11-14`；`ButlerPanel.vue:61-97`；后端 OpenAPI 无该 path。触发方式：教师在任一路由打开管家并点击“确认联网执行”。影响：Mock 可显示结果，真实环境必然失败；用户会看到“已确认”但没有第二次请求，形成假闭环。建议：要么接入正式 Butler Kernel chat 契约，要么从 M3 P0 UI 移除；确认必须产生可审计的二次执行请求。

**I-06 资源与异步任务链是占位实现，且上传/理解无班级 scope。** 证据：`D:\math-arena\services\api\app\domains\teacher\resources.py:56-135`、`router.py:360-392`；前端 `TeacherResourcesView.vue:66-76`。触发方式：选择本地文件提交资源，再点击预处理/理解。影响：真实文件未上传，任务只入队或返回占位，资源可跨班级/owner 检索边界不清。建议：multipart → resource ownership/class scope → durable task worker → status/result/artifact 全链路落库并测试。

**I-07 batch grading 没有幂等保护，并泄露不稳定异常文本。** 证据：`D:\math-arena\services\api\app\domains\teacher\router.py:324-341`。触发方式：重复提交 batch 或让其中一项触发异常。影响：重复正式评分风险；响应含 `str(exc)`，可能泄露内部/上游信息，且无法按 SSOT 错误码恢复。建议：每项使用稳定 client request/idempotency key，事务边界明确，返回 per-item stable code/message，不返回 raw exception。

**I-08 classes 页面把 wrapper 当数组，apply insight 只是 toast。** 证据：`D:\frontend\src/pages/teacher/TeacherClassesView.vue:58,75-76` 对比后端 `router.py:81-90`。触发方式：真实加载班级洞察或点击“应用洞察”。影响：数组渲染可能失败/为空；用户确认后没有写入教案草稿。建议：按统一 data shape 解包，并调用 `lessons/{id}/apply-insight`，确认成功后刷新 Artifact 状态。

### Minor

**M-01 E2E 名称与断言不匹配，Mock 容易假通过。** 证据：`D:\frontend\e2e\m3-teacher.spec.ts:84-88` 的 “upload -> preprocess -> understand” 只断言“材料”可见；`96-105` 直接访问 Mock route。触发方式：删除真实 API 或破坏上传字段，Mock E2E 仍可通过。影响：测试报告高估完成度。建议：增加真实后端 contract smoke；Mock 测试明确标注展示级，不计入联调通过。

**M-02 Today 的“下一节课”使用 assignment deadline 作为 starts_at。** 证据：`D:\math-arena\services\api\app\domains\teacher\today.py:125-156`。触发方式：存在作业截止时间但没有真实课表事件时查看 today。影响：教师可能把作业截止误认为上课时间。建议：区分 timetable lesson 与 assignment deadline；没有课表时明确显示“待办截止”而不是“下一节课”。

## 8. 对旧执行日志和 contract-gaps 的纠正

- `D:\frontend\.workbuddy\m3-teacher-frontend-execution-log.md` 记录 HEAD 为 `46b8e0b`，实际审查 HEAD 是 `f1b2646`；其“以 Mock 完成全部前端主链”不能证明真实联调。
- 后端执行日志没有完整记录真实 M3 提交链，且“测试/接口完成”没有覆盖本次当前 HEAD 的 11 个完整测试失败。
- `D:\frontend\.workbuddy\m3-backend-contract-gaps.md` 当时因 backend unavailable，只能列期望接口；其中 POST `/api/teacher/butler/chat` 被描述为“前端降级演示用、非正式 P0”，本次 OpenAPI 证据确认它仍不是后端正式契约，不能纳入 M3 已实现清单。
- 旧日志列出的“GET classroom 状态”是期望，不是当前后端实际路由；当前 OpenAPI 只有 POST classroom-mode。
- 旧日志中的前端 build/Vitest 结果可复现并更新为本次的 54 Vitest、production build 通过；但这些静态/Mock 结果不能抵消真实 API schema mismatch。

## 9. Go / Conditional Go / No-Go 门禁

| 门禁 | 结论 | 最小阻塞项 |
|---|---|---|
| 后端 | Conditional Go | 修正 C-01/C-02/C-03；修好 Artifact/assignment/grading 状态机和幂等测试；修复 Xingchen adapter；在临时 PostgreSQL 完成 upgrade smoke |
| 前端 | Conditional Go | 以 OpenAPI 契约重做 assignment/artifact/grading/resource/classroom wrappers；去除 Butler 假确认；补真实 loading/empty/error/degraded/permission 断言 |
| 前后端联调 | No-Go | C-04 必须清零；建立 `M3_ENABLE_TEACHER=true` 的真实 API 与前端 smoke，至少覆盖 adapt→confirm→slides、quiz→assignment→publish、suggest→confirm、upload→preprocess→understand |
| 集成演示 | No-Go | 不能用 Mock 代替正式演示；需有启用 profile、临时数据、真实后端、可审计确认和稳定降级的单命令启动与退出检查 |

## 10. 最短修复顺序（本报告不实施）

1. 先修 C-01/C-03 的鉴权和班级 scope，再把 C-02 的 capability 入口收敛到 Registry/Policy/Executor。
2. 冻结并生成前后端统一契约：envelope、action body、artifact/task response、错误码、`request_id`、幂等字段。
3. 修正 Artifact 状态机、版本乐观锁、assignment publish、grading confirm/batch 的事务和 replay 语义；让 M3 聚焦测试全绿。
4. 修正 Xingchen adapter async/signature，并为七工作流补 succeeded/degraded/failed 三态测试；明确本地 builder 哪些是真实规则、哪些仍是占位。
5. 重接前端七页面真实 API；特别是资源 multipart、课堂状态、洞察 apply、Butler 正式入口；将 Mock E2E 与真实 contract smoke 分开计数。
6. 在隔离临时 PostgreSQL 完成 Alembic upgrade/rollback 检查，配置教师 profile 后跑真实最小 smoke，再重新评估集成演示门禁。

本审查到此结束，未实施任何修复。
