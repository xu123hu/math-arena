# M3 教师端后端执行日志

> 依据：`D:\M2开发\M3教师端\_M3教师端后端全自动开发主提示词_v1.0.md`
> 目标：在 `D:\math-arena` 连续开发 M3 教师端后端，不中断到最终验收或真实停止条件。

## 基线
- 阶段 6 / 6A 绿色独立提交：`5054325`（feat: prewire butler web_search_opt_in transport chain）
- M3 基线 HEAD：`5054325`
- 工作区遗留修改（与本任务无关，绝不触碰/暂存/提交）：apps/web 删除项、.env.example、.gitignore、CI、多份未跟踪 `_diag_*`/scripts/eval 等

## 追踪矩阵（需求 → API → Service/Tool → 数据表 → 测试）
| 需求 | API | Service/Tool | 表 | 测试 |
|---|---|---|---|---|
| F0 Today | GET /api/teacher/today | today.py | 聚合 | test_m3_teacher_today_insights.py |
| F6 洞察 | GET /api/teacher/classes/{id}/insights | insights.py | actionable_insights | 同上 |
| F1 备课 | POST /api/teacher/lessons/adapt | lessons.py, capability_gateway | teaching_artifacts | test_m3_teacher_lessons.py |
| F3 作业/出题 | POST /api/teacher/quizzes/generate | assessment.py | teaching_artifacts+assignments | test_m3_teacher_assessment.py |
| F4 批改 | grading/suggest/confirm | grading.py | submission_items+teaching_artifacts | test_m3_teacher_grading.py |
| F7 课堂 | POST classroom-mode / video-insights | classroom.py | — | test_m3_teacher_classroom.py |
| F2/F11 课件/讲解 | lessons/slides, lessons/explainer | lessons.py | teaching_artifacts | test_m3_teacher_lessons.py |
| 资源 | resources/upload/preprocess/understand | resources.py | teacher_tasks | test_m3_teacher_resources.py |
| Capability | POST /api/ai/capabilities/{cap} | capability_gateway.py, registry.py | teaching_artifacts | test_m3_teacher_capabilities.py |
| Artifact | artifacts/* | artifacts.py | teaching_artifacts+teacher_actions | test_m3_teacher_artifacts.py |
| 范围 | — | scope.py | class_members | test_m3_teacher_scope.py |
| 任务 | tasks/* | — | teacher_tasks | test_m3_teacher_resources.py |
| channel | 全部 | registry_policy.py | — | test_m3_teacher_registry_policy.py |
| E2E | 全部 | — | — | test_m3_teacher_e2e.py |

## 提交链
- 待定（每完成一个逻辑块独立提交）
# 2026-08-21 审计重建续跑

- 阶段 6 绿色基线：`5054325`；M3 审计起点：`d453235`。
- 当前工作区有大量既有非 M3 修改；本任务只精确暂存 M3 文件。
- 已完整读取 v2.1 产品/API/前端/工作流 SSOT 和前端实际 API/Store。
- 已完成当前 HEAD 代码审计、GitHub 四方向核验和师生联动设计。
- RED：M3 初跑 7 个 Artifact 用例因 pytest-asyncio session fixture 跨 loop 失败。
- GREEN：`seeded` fixture 改为 function loop；Artifact 7/7、M3 58/58。
- 已确认缺口：管理员工作流 8 路由/字段、数据库驱动 Adapter、未配置降级标记、Butler chat、学生课堂读取。
- 下一条命令：`.venv\Scripts\python.exe -m pytest tests/test_workflow_configs.py -q --tb=short`。

## 2026-08-22 重建完成记录

- 工作流管理面：补齐列表、单项、创建、更新、删除、测试、启用、禁用 8 个动作；凭证 Fernet 密文保存，响应不回显；支持旧 `flow_id/timeout` 字段。
- Adapter：改为读取数据库 per-flow 配置；configured/verified/available 任一不满足即本地降级；超时、Schema 异常和上游错误统一规范化；安全文本能力最多重试 1 次。
- ButlerPanel：新增 `POST /api/teacher/butler/chat`，复用唯一 Butler Kernel；固定教师角色并校验 scene、class、artifact scope；WRITE 返回确认要求，不产生正式业务写入。
- 师生联动：新增学生/教师 scoped 的 `GET /api/classes/{class_id}/classroom-mode`；非成员按 404 防枚举，TTL 过期回到 inactive。
- Registry 风险分层：7 READ、7 LEARNING_ACTION、5 WRITE，共 19 个具名教师工具；教师域不含科研能力。
- 数据库：`math-arena-dev` 隔离 PostgreSQL 从空库升级至 `m3_001_teacher_core (head)`；官方种子写入 5 个知识点、1 个文档、15 个切片。
- RED→GREEN：工作流管理 405/字段缺失→2 例通过；未配置降级标记错误→通过；Butler 404→通过；学生课堂入口缺失→通过；配置变化未使验证失效→通过；风险计数 14 READ→7/7/5。
- 聚焦回归：`test_m3_teacher_*.py` 68/68 通过（14.86s）；新增 Redis 故障不阻断数据库配置的回归用例。
- OpenAPI：M3 开启时 33 条教师路径 / 37 个操作；另含学生课堂读取后为 34 条相关路径 / 38 个操作。默认 `M3_ENABLE_TEACHER=false` 时不挂教师路径。
- 全量回归首次为 1300 passed / 6 skipped / 2 failed；两项根因分别是空开发库未种知识点、M2 profile 用例未显式关闭 M3。两项均已修复并定向通过，最终全量数字见本日志后续验收条目。
- 迁移往返：`m3_001_teacher_core -> m2_018_butler_kernel_v2_ledger -> m3_001_teacher_core` 成功，`alembic heads/current` 均为唯一 `m3_001_teacher_core (head)`。
- 静态检查：本轮变更文件 Ruff 全绿；`git diff --check` 无空白错误（仅 Windows CRLF 提示）。
- 类型检查：安装项目已声明的 Mypy 后执行严格检查，因仓库既有跨模块类型债务失败（大量无参数 `dict/list`、缺少第三方 stubs、旧模块返回类型问题）；未把全仓类型化扩大进 M3 任务。
- 最终全量回归：`1305 passed, 6 skipped in 645.81s`。
- 提交隔离验收：从提交 HEAD 仅导出 `services/api` archive（规避 Windows tar 对仓库历史中文文件名的编码限制），应用导入成功，1307 项 collect-only 成功，archive 内 M3 68/68 通过。
