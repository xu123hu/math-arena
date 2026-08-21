# M3 Teacher Backend Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留当前 M3 绿色核心的前提下，补齐工作流配置、数据库驱动降级、ButlerPanel、学生课堂同步和最终验收。

**Architecture:** 教师业务继续位于独立 teacher domain；工作流配置复用 SystemConfig 和 Fernet；Butler Kernel 仍是唯一 Runtime；M2 Assignment/Submission/Class 是师生联动的唯一数据真相。

**Tech Stack:** FastAPI、SQLAlchemy async、PostgreSQL 15/pgvector、Pydantic、Butler Kernel v2、pytest。

**Spec:** `D:/WorkBuddy_M3教师端后端主提示词_v2.0_审计重建版.md`

## Global Constraints

- 不修改 `D:\frontend`，只读取真实调用契约。
- `M3_ENABLE_TEACHER=false` 默认不挂教师路由。
- 不修改学生聊天语义或 student Registry。
- 所有正式写操作要求教师确认、幂等与审计。
- 7 Capability、7 工作流、19 个具名 teacher tools；不恢复科研能力。
- 新行为必须先有失败测试，并保留 RED→GREEN 命令证据。

---

### Task 1: 工作流配置与管理员 8 路由

**Files:**
- Create: `services/api/app/domains/teacher/workflow_config.py`
- Modify: `services/api/app/gateway/admin_router.py`
- Test: `services/api/tests/test_workflow_configs.py`

**Interfaces:**
- Consumes: `SystemConfig`, `encrypt_api_key`, `decrypt_api_key`, `run_workflow`。
- Produces: `resolve_teacher_workflow(db, capability)` 与 8 条 `/api/admin/workflows*` 动作。

- [x] 写 CRUD、admin-only、密文和 configured/verified/available 失败测试。
- [x] 运行工作流配置测试，确认 405/字段缺失 RED。
- [x] 实现兼容旧 `flow_id/timeout` 的配置服务和路由。
- [x] 重跑新测试与 `tests/test_admin.py` 得到 GREEN。

### Task 2: 数据库驱动 Adapter 与正确降级

**Files:**
- Modify: `services/api/app/domains/teacher/workflow_adapter.py`
- Modify: `services/api/app/domains/teacher/capability_gateway.py`
- Test: `services/api/tests/test_workflow_teacher_adapter.py`

**Interfaces:**
- Consumes: `resolve_teacher_workflow`。
- Produces: succeeded/degraded/failed 规范结果；未配置本地产物必须 `degraded=true`。

- [x] 写未配置、禁用、未验证、成功、超时和 Schema 非法测试并观察 RED。
- [x] 把解析后的 per-flow 配置传入 `run_workflow(config=...)`。
- [x] 验证原始异常/密钥不出响应，7 能力均能本地降级。

### Task 3: ButlerPanel 正式入口

**Files:**
- Create: `services/api/app/domains/teacher/butler.py`
- Modify: `services/api/app/domains/teacher/router.py`
- Test: `services/api/tests/test_m3_teacher_butler_chat.py`

**Interfaces:**
- Consumes: `build_teacher_registry`, `PolicyGate`, `run_capability`。
- Produces: `POST /api/teacher/butler/chat`，只接受 scene/class/artifact/message/clientRequestId。

- [x] 写角色、scene、class scope、只读回复、生成 draft、WRITE confirmation_required 测试。
- [x] 实现受约束的教师规划提示和具名工具路由，不暴露思维链/Provider/工作流名。
- [x] 验证 WRITE 被 Policy 拦截并返回 confirmation_required，不产生业务副作用。

### Task 4: 学生课堂状态同步

**Files:**
- Modify: `services/api/app/domains/classroom/router.py`
- Test: `services/api/tests/test_m3_teacher_student_classroom.py`

**Interfaces:**
- Consumes: `ClassroomMode`, class membership。
- Produces: `GET /api/classes/{class_id}/classroom-mode` 的学生/教师 scoped 只读状态。

- [x] 写成员成功、外班拒绝、TTL 过期测试并观察 RED。
- [x] 实现共享读取且不改学生聊天语义。

### Task 5: 文档、契约与数据验收

**Files:**
- Modify: `docs/workbuddy/2026-08-20-m3-teacher-backend-execution-log.md`
- Modify: `docs/workbuddy/m3-teacher-backend-audit.md`

**Interfaces:**
- Consumes: OpenAPI、前端只读 API、Alembic、测试结果。
- Produces: 路径对照、迁移往返、密钥扫描和恢复命令。

- [x] 核对前端 11 个 API 文件与 OpenAPI 方法/路径/信封。
- [x] 在隔离 PostgreSQL 执行 upgrade→downgrade→upgrade 和单 head。
- [x] 运行 M3、Butler、workflow、ruff、mypy、完整 pytest、diff check（Mypy 暴露既有全仓类型债务，详见执行日志）。
- [x] 从提交 HEAD 做 archive 导入与 collect-only 验证。
